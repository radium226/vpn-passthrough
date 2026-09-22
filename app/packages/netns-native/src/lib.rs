//! Replaces the `ip link add/set`, `ip addr add`, `ip route add` subprocess
//! calls in `network_interfaces.py` with direct netlink requests.
//!
//! Host-side link/address setup happens in this process's own network
//! namespace. Configuring the peer once it has been moved into the tunnel's
//! namespace requires `setns()`, which is thread-directed and therefore
//! cannot be done from a thread of an already-running multi-threaded tokio
//! runtime — so we tear the host-side runtime down, `fork()` (no `exec`),
//! `setns()` in the child, and report success/failure back through a pipe.

use std::fs::File;
use std::net::{IpAddr, Ipv4Addr};
use std::os::fd::{AsFd, OwnedFd};

use futures::stream::TryStreamExt;
use nix::sched::{setns, CloneFlags};
use nix::sys::wait::waitpid;
use nix::unistd::{fork, pipe, read, write, ForkResult};
use pyo3::exceptions::PyOSError;
use pyo3::prelude::*;
use rtnetlink::{new_connection, Handle, LinkUnspec, LinkVeth, RouteMessageBuilder};

fn to_pyerr(e: impl std::fmt::Display) -> PyErr {
    PyOSError::new_err(e.to_string())
}

fn parse_ipv4(label: &str, value: &str) -> Result<Ipv4Addr, String> {
    value
        .parse()
        .map_err(|_| format!("invalid {label}: {value:?}"))
}

fn parse_extra_routes(routes: &[String]) -> Result<Vec<(Ipv4Addr, u8)>, String> {
    routes
        .iter()
        .map(|route| {
            let (addr, prefix) = route
                .split_once('/')
                .ok_or_else(|| format!("invalid CIDR route: {route:?}"))?;
            let addr = parse_ipv4("route address", addr)?;
            let prefix: u8 = prefix
                .parse()
                .map_err(|_| format!("invalid prefix in route: {route:?}"))?;
            Ok((addr, prefix))
        })
        .collect()
}

async fn link_index(handle: &Handle, name: &str) -> Result<u32, String> {
    let mut links = handle.link().get().match_name(name.to_string()).execute();
    let link = links
        .try_next()
        .await
        .map_err(|e| format!("look up link {name}: {e}"))?
        .ok_or_else(|| format!("link {name} not found"))?;
    Ok(link.header.index)
}

async fn set_link_up(handle: &Handle, index: u32) -> Result<(), String> {
    handle
        .link()
        .change(LinkUnspec::new_with_index(index).up().build())
        .execute()
        .await
        .map_err(|e| format!("bring link {index} up: {e}"))
}

/// Create the veth pair, address + bring up the host end, and move the peer
/// into the target namespace. Runs entirely in the current (host) netns.
async fn host_side_setup(
    veth: &str,
    vpeer: &str,
    veth_ip: Ipv4Addr,
    prefix_len: u8,
    netns_pid: u32,
) -> Result<(), String> {
    let (connection, handle, _) = new_connection().map_err(|e| e.to_string())?;
    tokio::spawn(connection);

    handle
        .link()
        .add(LinkVeth::new(veth, vpeer).build())
        .execute()
        .await
        .map_err(|e| format!("create veth pair {veth}/{vpeer}: {e}"))?;

    let veth_idx = link_index(&handle, veth).await?;
    handle
        .address()
        .add(veth_idx, IpAddr::V4(veth_ip), prefix_len)
        .execute()
        .await
        .map_err(|e| format!("assign {veth_ip}/{prefix_len} to {veth}: {e}"))?;
    set_link_up(&handle, veth_idx).await?;

    let vpeer_idx = link_index(&handle, vpeer).await?;
    handle
        .link()
        .change(LinkUnspec::new_with_index(vpeer_idx).setns_by_pid(netns_pid).build())
        .execute()
        .await
        .map_err(|e| format!("move {vpeer} into netns pid {netns_pid}: {e}"))?;

    Ok(())
}

/// Address + bring up the peer, bring up loopback, and add routes. Must run
/// after `setns()` into the target namespace.
fn netns_side_setup(
    vpeer: &str,
    vpeer_ip: Ipv4Addr,
    prefix_len: u8,
    gateway_ip: Ipv4Addr,
    extra_routes: &[(Ipv4Addr, u8)],
) -> Result<(), String> {
    let rt = tokio::runtime::Runtime::new().map_err(|e| e.to_string())?;
    rt.block_on(async {
        let (connection, handle, _) = new_connection().map_err(|e| e.to_string())?;
        tokio::spawn(connection);

        let vpeer_idx = link_index(&handle, vpeer).await?;
        handle
            .address()
            .add(vpeer_idx, IpAddr::V4(vpeer_ip), prefix_len)
            .execute()
            .await
            .map_err(|e| format!("assign {vpeer_ip}/{prefix_len} to {vpeer}: {e}"))?;
        set_link_up(&handle, vpeer_idx).await?;

        let lo_idx = link_index(&handle, "lo").await?;
        set_link_up(&handle, lo_idx).await?;

        handle
            .route()
            .add(RouteMessageBuilder::<Ipv4Addr>::new().gateway(gateway_ip).build())
            .execute()
            .await
            .map_err(|e| format!("add default route via {gateway_ip}: {e}"))?;

        for (dest, dest_prefix) in extra_routes {
            handle
                .route()
                .add(
                    RouteMessageBuilder::<Ipv4Addr>::new()
                        .destination_prefix(*dest, *dest_prefix)
                        .gateway(gateway_ip)
                        .build(),
                )
                .execute()
                .await
                .map_err(|e| format!("add route {dest}/{dest_prefix} via {gateway_ip}: {e}"))?;
        }

        Ok::<(), String>(())
    })
}

fn enter_net_namespace(pid: u32) -> Result<(), String> {
    let file = File::open(format!("/proc/{pid}/ns/net"))
        .map_err(|e| format!("open /proc/{pid}/ns/net: {e}"))?;
    setns(file.as_fd(), CloneFlags::CLONE_NEWNET).map_err(|e| format!("setns: {e}"))
}

fn read_exact(fd: &OwnedFd, buf: &mut [u8]) -> nix::Result<()> {
    let mut offset = 0;
    while offset < buf.len() {
        let n = read(fd, &mut buf[offset..])?;
        if n == 0 {
            return Err(nix::errno::Errno::EIO);
        }
        offset += n;
    }
    Ok(())
}

/// Equivalent of `NetworkInterfaces.add()`'s `ip` invocations: create a veth
/// pair, configure the host side, move the peer into `netns_pid`, and
/// configure the peer side (address, up, default route, extra routes).
#[pyfunction]
#[pyo3(signature = (veth, vpeer, veth_ip, vpeer_ip, prefix_len, netns_pid, extra_routes=vec![]))]
fn add_veth_pair(
    veth: String,
    vpeer: String,
    veth_ip: String,
    vpeer_ip: String,
    prefix_len: u8,
    netns_pid: u32,
    extra_routes: Vec<String>,
) -> PyResult<()> {
    let veth_addr = parse_ipv4("veth_ip", &veth_ip).map_err(to_pyerr)?;
    let vpeer_addr = parse_ipv4("vpeer_ip", &vpeer_ip).map_err(to_pyerr)?;
    let routes = parse_extra_routes(&extra_routes).map_err(to_pyerr)?;

    let rt = tokio::runtime::Runtime::new().map_err(to_pyerr)?;
    rt.block_on(host_side_setup(&veth, &vpeer, veth_addr, prefix_len, netns_pid))
        .map_err(to_pyerr)?;
    // Fully shut down the runtime (and its threads) before forking: a
    // multi-threaded tokio runtime does not survive fork() in the child.
    drop(rt);

    let (read_fd, write_fd) = pipe().map_err(to_pyerr)?;
    match unsafe { fork() }.map_err(to_pyerr)? {
        ForkResult::Child => {
            drop(read_fd);
            let result = enter_net_namespace(netns_pid)
                .and_then(|()| netns_side_setup(&vpeer, vpeer_addr, prefix_len, veth_addr, &routes));
            let message = result.err().unwrap_or_default();
            let _ = write(&write_fd, &(message.len() as u32).to_le_bytes());
            let _ = write(&write_fd, message.as_bytes());
            drop(write_fd);
            std::process::exit(if message.is_empty() { 0 } else { 1 });
        }
        ForkResult::Parent { child } => {
            drop(write_fd);
            let mut len_buf = [0u8; 4];
            read_exact(&read_fd, &mut len_buf).map_err(to_pyerr)?;
            let len = u32::from_le_bytes(len_buf) as usize;
            let mut message_buf = vec![0u8; len];
            if len > 0 {
                read_exact(&read_fd, &mut message_buf).map_err(to_pyerr)?;
            }
            drop(read_fd);
            waitpid(child, None).map_err(to_pyerr)?;
            if !message_buf.is_empty() {
                return Err(PyOSError::new_err(String::from_utf8_lossy(&message_buf).into_owned()));
            }
            Ok(())
        }
    }
}

/// Equivalent of `ip link delete <name>`. Deleting the host end of a veth
/// pair also removes its peer.
#[pyfunction]
fn delete_link(name: String) -> PyResult<()> {
    let rt = tokio::runtime::Runtime::new().map_err(to_pyerr)?;
    rt.block_on(async {
        let (connection, handle, _) = new_connection().map_err(|e| e.to_string())?;
        tokio::spawn(connection);
        let idx = link_index(&handle, &name).await?;
        handle
            .link()
            .del(idx)
            .execute()
            .await
            .map_err(|e| format!("delete link {name}: {e}"))
    })
    .map_err(to_pyerr)
}

#[pymodule]
fn netns_native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(add_veth_pair, m)?)?;
    m.add_function(wrap_pyfunction!(delete_link, m)?)?;
    Ok(())
}
