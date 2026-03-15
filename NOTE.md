# Systemd Property Inheritance via vpn-passthrough run-process

When a systemd service uses `ExecStart=vpn-passthrough run-process --in-tunnel="..." -- some-daemon`,
`some-daemon` is spawned by the vpn-passthrough **server** process, not by the calling service.
This breaks most systemd sandbox properties.

## The Flow

```
systemd service A  →  vpn-passthrough run-process  →  [Unix socket]  →  server spawns some-daemon
     cgroup: A's slice                                                        cgroup: server's slice
     mount ns: A's (PrivateTmp, etc.)                                         mount ns: tunnel's
```

## What `make_preexec_fn` Does

Enters two namespaces from the tunnel's `unshare` process (the `tail -f /dev/null` holder):
1. The tunnel's **mount namespace** — has `resolv.conf` and `nsswitch.conf` bind mounts for DNS isolation
2. The tunnel's **network namespace** — the VPN

## The Mount Namespace Conflict (and Solution)

At first glance `some-daemon` cannot simultaneously be in:
- The tunnel's mount namespace (required — that's where DNS resolution works)
- The calling service's mount namespace (`PrivateTmp=yes`, `BindPaths=`, etc.)

But this **can** be resolved by creating a **child mount namespace** from the caller's,
then layering the tunnel's DNS bind mounts on top.

### How: child mount namespace via `unshare(CLONE_NEWNS)`

In `preexec_fn`, instead of entering the tunnel's existing mount namespace directly:

1. `setns(caller_mnt_fd, CLONE_NEWNS)` — enter the calling service's mount namespace
2. `os.unshare(CLONE_NEWNS)` — fork a private child copy (doesn't pollute the caller's ns)
3. Bind-mount the tunnel's `resolv.conf` and `nsswitch.conf` over `/etc` (requires root, happens before privilege drop)
4. `setns(tunnel_net_fd, CLONE_NEWNET)` — enter the VPN network namespace

Result: caller's mounts (PrivateTmp, ReadOnlyPaths, etc.) **+** tunnel DNS **+** VPN network.

The tunnel's own mount namespace (the `tail -f /dev/null` holder) is left unchanged.
Each spawned process gets its own private child mount namespace.

```python
# caller_mnt_fd passed via SCM_RIGHTS (optional — falls back to tunnel's mnt ns if absent)

def _preexec():
    if caller_mnt_fd is not None:
        _setns(caller_mnt_fd, CLONE_NEWNS)
        os.close(caller_mnt_fd)
        os.unshare(os.CLONE_NEWNS)   # Python 3.12+; forks a child copy

        # Overlay tunnel DNS files (must happen before privilege drop)
        # /etc/resolv.conf is often a symlink — replace it with a regular file first
        resolv = Path("/etc/resolv.conf")
        if resolv.is_symlink():
            resolv.unlink()
            resolv.touch()
        libc.mount(str(resolv_conf_path).encode(), b"/etc/resolv.conf", None, MS_BIND, None)
        libc.mount(str(nsswitch_conf_path).encode(), b"/etc/nsswitch.conf", None, MS_BIND, None)
    else:
        _setns(mnt_fd, CLONE_NEWNS)   # current behaviour
        os.close(mnt_fd)

    _setns(net_fd, CLONE_NEWNET)
    os.close(net_fd)

    # ... privilege drop as before ...
```

`resolv_conf_path` and `nsswitch_conf_path` are the files already written by `dns.py` at
`{base_folder_path}/{tunnel_name}/resolv.conf` (and `nsswitch.conf`) — no new files needed.

## Property-by-Property Breakdown

| Property | Inherited? | Notes |
|---|---|---|
| Mount namespace (`PrivateTmp`, `BindPaths`, etc.) | **Yes (with child ns approach)** | Enter caller's mnt ns, unshare, overlay DNS |
| Network namespace | **Yes** | That's the whole point |
| Cgroup / slice | No | Can be fixed via cgroup fd passing |
| Resource limits (`LimitNOFILE`, etc.) | No | Can be passed as values + `setrlimit()` in `preexec_fn` |
| Environment variables | Yes | `RunProcess.env` already handles this |
| User/group | Yes | Already handled |
| Capabilities | Partial | `ambient_capabilities` param exists |
| Seccomp (`SystemCallFilter=`) | **No, can't be** | Per-thread, not transferable across fork |
| IPC namespace (`PrivateIPC=`) | No | Technically passable via ns fd + `setns`, rarely worth it |
| UTS namespace | No | Same |
| AppArmor / SELinux label | **No, can't be** | Not transferable |

## What Can Be Implemented

### 1. Mount namespace inheritance (child ns approach)

As described above. The client passes `/proc/self/ns/mnt` as an extra fd via SCM_RIGHTS.
`make_preexec_fn` gains optional `caller_mnt_fd`, `resolv_conf_path`, `nsswitch_conf_path` params.

### 2. Cgroup inheritance

The client opens its own cgroup directory fd and passes it as an extra fd via the existing
SCM_RIGHTS mechanism (after stdin/stdout/stderr). The server writes the spawned PID to
`cgroup.procs` via that fd after spawning.

**Client:**
```python
def open_own_cgroup_fd() -> int:
    with open("/proc/self/cgroup") as f:
        cgroup_rel = f.read().splitlines()[0].split("::", 1)[1]
    return os.open(f"/sys/fs/cgroup{cgroup_rel}", os.O_RDONLY | os.O_DIRECTORY)

cgroup_fd = open_own_cgroup_fd()
await client.run_process("some-daemon", [], fds=[stdin, stdout, stderr, cgroup_fd])
```

**Server** (after spawn):
```python
if cgroup_fd is not None:
    procs_fd = os.open("cgroup.procs", os.O_WRONLY, dir_fd=cgroup_fd)
    try:
        os.write(procs_fd, str(process.pid).encode())
    finally:
        os.close(procs_fd)
        os.close(cgroup_fd)
```

There is a brief race where the process lives in the server's cgroup before being moved,
which is negligible for most purposes. The alternative (Linux 5.14+) is `clone3(CLONE_INTO_CGROUP)`
to spawn atomically into the target cgroup, but requires bypassing `asyncio.create_subprocess_exec`.

### 3. Resource limits

Add a `rlimits: dict[str, int]` field to `RunProcess` and call `resource.setrlimit()` in
`preexec_fn`. The client can read its own limits via `resource.getrlimit()`.

## Practical Conclusion

The child mount namespace approach cleanly composes the caller's sandbox with the VPN tunnel.
Seccomp and AppArmor still cannot be inherited — configure those on the vpn-passthrough
server's systemd unit if needed.
