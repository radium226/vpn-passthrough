//! Replaces the `nft -f -` subprocess calls in `kill_switch.py` (and, next,
//! `dns_leak_guard.py` / `internet.py`) with direct netlink requests via
//! `rustables` (libnftnl/libmnl over NETLINK_NETFILTER) — no `nft` binary
//! involved at runtime.

use std::fs::File;
use std::net::IpAddr;
use std::os::fd::{AsFd, OwnedFd};

use ipnetwork::IpNetwork;
use nix::sched::{setns, CloneFlags};
use nix::sys::wait::waitpid;
use nix::unistd::{fork, pipe, read, write, ForkResult};
use pyo3::exceptions::PyOSError;
use pyo3::prelude::*;
use rustables::error::BuilderError;
use rustables::{
    Batch, Chain, ChainPolicy, ChainType, Hook, HookClass, MsgType, Protocol, ProtocolFamily,
    Rule, Table,
};

fn to_pyerr(e: impl std::fmt::Display) -> PyErr {
    PyOSError::new_err(e.to_string())
}

fn table(name: &str) -> Table {
    Table::new(ProtocolFamily::Inet).with_name(name)
}

enum Direction {
    In,
    Out,
}

/// Adds two drop rules to `chain` (one for TCP, one for UDP), equivalent to
/// nft's `meta l4proto {tcp, udp} th dport 53 drop` on the given interface.
fn add_dns_drop_rules(
    chain: &Chain,
    batch: &mut Batch,
    iface: &str,
    direction: Direction,
) -> Result<(), BuilderError> {
    for protocol in [Protocol::TCP, Protocol::UDP] {
        let rule = Rule::new(chain)?;
        let rule = match direction {
            Direction::In => rule.iiface(iface)?,
            Direction::Out => rule.oiface(iface)?,
        };
        rule.dport(53, protocol).drop().add_to_batch(batch);
    }
    Ok(())
}

/// Runs `f` after `setns()`-ing into `netns_pid`'s network namespace, in a
/// forked child process, and reports success/failure back through a pipe.
/// Needed because configuring a namespace's *own* netfilter tables requires
/// a netlink socket opened from inside that namespace.
fn run_in_net_namespace(netns_pid: u32, f: impl FnOnce() -> Result<(), String>) -> PyResult<()> {
    let (read_fd, write_fd) = pipe().map_err(to_pyerr)?;
    match unsafe { fork() }.map_err(to_pyerr)? {
        ForkResult::Child => {
            drop(read_fd);
            let result = enter_net_namespace(netns_pid).and_then(|()| f());
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

/// Equivalent of `KillSwitch.activate()`'s ruleset: a forward chain (policy
/// accept) with explicit accepts for the VPN server and any extra routes,
/// then a catch-all drop for everything else leaving this tunnel's veth.
#[pyfunction]
#[pyo3(signature = (table_name, veth, server_ip, extra_routes=vec![]))]
fn install_kill_switch(
    table_name: String,
    veth: String,
    server_ip: String,
    extra_routes: Vec<String>,
) -> PyResult<()> {
    let server_addr: IpAddr = server_ip
        .parse()
        .map_err(|_| PyOSError::new_err(format!("invalid server_ip: {server_ip:?}")))?;
    let routes: Vec<IpNetwork> = extra_routes
        .iter()
        .map(|route| {
            route
                .parse()
                .map_err(|_| PyOSError::new_err(format!("invalid CIDR route: {route:?}")))
        })
        .collect::<PyResult<_>>()?;

    let mut batch = Batch::new();
    let table = table(&table_name).add_to_batch(&mut batch);

    let chain = Chain::new(&table)
        .with_name("forward")
        .with_type(ChainType::Filter)
        .with_hook(Hook::new(HookClass::Forward, 0))
        .with_policy(ChainPolicy::Accept)
        .add_to_batch(&mut batch);

    for route in &routes {
        Rule::new(&chain)
            .map_err(to_pyerr)?
            .iiface(&veth)
            .map_err(to_pyerr)?
            .dnetwork(*route)
            .map_err(to_pyerr)?
            .accept()
            .add_to_batch(&mut batch);
    }

    Rule::new(&chain)
        .map_err(to_pyerr)?
        .iiface(&veth)
        .map_err(to_pyerr)?
        .daddr(server_addr)
        .accept()
        .add_to_batch(&mut batch);

    Rule::new(&chain)
        .map_err(to_pyerr)?
        .iiface(&veth)
        .map_err(to_pyerr)?
        .drop()
        .add_to_batch(&mut batch);

    batch.send().map_err(to_pyerr)
}

/// Host-side half of `DNSLeakGuard.activate()`: a forward chain dropping any
/// DNS (TCP/UDP 53) coming in through the tunnel's veth. Runs in the host's
/// own network namespace, so it has full CAP_NET_ADMIN and always applies.
#[pyfunction]
fn install_dns_leak_guard_host(table_name: String, veth: String) -> PyResult<()> {
    let mut batch = Batch::new();
    let table = table(&table_name).add_to_batch(&mut batch);
    let chain = Chain::new(&table)
        .with_name("forward")
        .with_type(ChainType::Filter)
        .with_hook(Hook::new(HookClass::Forward, 0))
        .with_policy(ChainPolicy::Accept)
        .add_to_batch(&mut batch);

    add_dns_drop_rules(&chain, &mut batch, &veth, Direction::In).map_err(to_pyerr)?;
    batch.send().map_err(to_pyerr)
}

/// Netns-side half of `DNSLeakGuard.activate()`: defense-in-depth, dropping
/// outbound DNS from inside the tunnel's own network namespace. Best-effort
/// by design (see the docstring on the Python caller) — Python decides
/// whether a failure here is fatal, this just reports success or an error.
#[pyfunction]
fn install_dns_leak_guard_netns(table_name: String, vpeer: String, netns_pid: u32) -> PyResult<()> {
    run_in_net_namespace(netns_pid, move || {
        let mut batch = Batch::new();
        let table = table(&table_name).add_to_batch(&mut batch);
        let chain = Chain::new(&table)
            .with_name("output")
            .with_type(ChainType::Filter)
            .with_hook(Hook::new(HookClass::Out, 0))
            .with_policy(ChainPolicy::Accept)
            .add_to_batch(&mut batch);

        add_dns_drop_rules(&chain, &mut batch, &vpeer, Direction::Out).map_err(|e| e.to_string())?;
        batch.send().map_err(|e| e.to_string())
    })
}

/// Equivalent of `nft delete table inet <name>` — used by all three
/// tables (kill switch, dns leak guard, internet sharing) on teardown.
#[pyfunction]
fn delete_table(table_name: String) -> PyResult<()> {
    let mut batch = Batch::new();
    batch.add(&table(&table_name), MsgType::Del);
    batch.send().map_err(to_pyerr)
}

/// Same as `delete_table`, but run inside `netns_pid`'s network namespace —
/// for tearing down the dns_leak_guard netns-side table.
#[pyfunction]
fn delete_table_in_netns(table_name: String, netns_pid: u32) -> PyResult<()> {
    run_in_net_namespace(netns_pid, move || {
        let mut batch = Batch::new();
        batch.add(&table(&table_name), MsgType::Del);
        batch.send().map_err(|e| e.to_string())
    })
}

#[pymodule]
fn nftables_native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(install_kill_switch, m)?)?;
    m.add_function(wrap_pyfunction!(install_dns_leak_guard_host, m)?)?;
    m.add_function(wrap_pyfunction!(install_dns_leak_guard_netns, m)?)?;
    m.add_function(wrap_pyfunction!(delete_table, m)?)?;
    m.add_function(wrap_pyfunction!(delete_table_in_netns, m)?)?;
    Ok(())
}
