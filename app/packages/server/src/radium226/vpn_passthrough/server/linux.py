import os
import pwd
import resource
import ctypes
from collections.abc import Callable
from pathlib import Path

from loguru import logger

from .client_process import SOCK_FILTER_SIZE, ClientProcess, ClientProcessError

# Namespace constants
CLONE_NEWNS     = 0x00020000
CLONE_NEWNET    = 0x40000000
CLONE_NEWUTS    = 0x04000000
CLONE_NEWIPC    = 0x08000000
CLONE_NEWCGROUP = 0x02000000

# Mount constants
MS_REC = 0x4000
MS_SLAVE = 0x80000

# open_tree and move_mount: the same number on every architecture
SYS_OPEN_TREE = 428
SYS_MOVE_MOUNT = 429
OPEN_TREE_CLONE = 1
AT_FDCWD = -100
AT_EMPTY_PATH = 0x1000
MOVE_MOUNT_F_EMPTY_PATH = 0x4
MOVE_MOUNT_T_SYMLINKS = 0x10

# Capability constants
PR_SET_KEEPCAPS = 8
PR_CAPBSET_DROP = 24
PR_SET_NO_NEW_PRIVS = 38
CAP_SYS_ADMIN = 21

# seccomp constants
PR_SET_SECCOMP = 22
SECCOMP_MODE_FILTER = 2
PR_CAP_AMBIENT = 47
PR_CAP_AMBIENT_RAISE = 2
_LINUX_CAPABILITY_VERSION_3 = 0x20080522

# Default Docker/Podman container capabilities
_CONTAINER_CAPS = frozenset({
    0,   # CAP_CHOWN
    1,   # CAP_DAC_OVERRIDE
    3,   # CAP_FOWNER
    4,   # CAP_FSETID
    5,   # CAP_KILL
    6,   # CAP_SETGID
    7,   # CAP_SETUID
    8,   # CAP_SETPCAP
    10,  # CAP_NET_BIND_SERVICE
    13,  # CAP_NET_RAW
    18,  # CAP_SYS_CHROOT
    27,  # CAP_MKNOD
    29,  # CAP_AUDIT_WRITE
    31,  # CAP_SETFCAP
})

libc = ctypes.CDLL("libc.so.6", use_errno=True)
libc.setns.argtypes = [ctypes.c_int, ctypes.c_int]
libc.setns.restype = ctypes.c_int
libc.prctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]
libc.prctl.restype = ctypes.c_int
libc.capget.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
libc.capget.restype = ctypes.c_int
libc.capset.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
libc.capset.restype = ctypes.c_int
libc.mount.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_ulong, ctypes.c_void_p]
libc.mount.restype = ctypes.c_int
libc.syscall.restype = ctypes.c_long


class _CapHeader(ctypes.Structure):
    _fields_ = [("version", ctypes.c_uint32), ("pid", ctypes.c_int)]


class _SockFprog(ctypes.Structure):
    _fields_ = [("len", ctypes.c_ushort), ("filter", ctypes.c_void_p)]


class _CapData(ctypes.Structure):
    _fields_ = [
        ("effective", ctypes.c_uint32),
        ("permitted", ctypes.c_uint32),
        ("inheritable", ctypes.c_uint32),
    ]


def _setns(fd: int, nstype: int) -> None:
    if libc.setns(fd, nstype) != 0:
        errno = ctypes.get_errno()
        raise OSError(errno, os.strerror(errno), "setns")


def _check(result: int, what: str) -> None:
    if result != 0:
        errno = ctypes.get_errno()
        raise OSError(errno, os.strerror(errno), what)


def _mount(source: str | None, target: str, flags: int) -> None:
    _check(libc.mount(source.encode() if source else None, target.encode(), None, flags, None), f"mount {target}")


def _open_tree(fd: int) -> int:
    """A copy of the mount of the file, detached: which, unlike the file, may be mounted in another namespace."""
    tree_fd = libc.syscall(SYS_OPEN_TREE, ctypes.c_int(fd), b"", ctypes.c_uint(OPEN_TREE_CLONE | AT_EMPTY_PATH | os.O_CLOEXEC))
    if tree_fd < 0:
        errno = ctypes.get_errno()
        raise OSError(errno, os.strerror(errno), "open_tree")
    return tree_fd


def _move_mount(tree_fd: int, target: str) -> None:
    """Mount the detached tree on the target, which, if a symlink (/etc/resolv.conf often is), is followed."""
    result = libc.syscall(
        SYS_MOVE_MOUNT,
        ctypes.c_int(tree_fd),
        b"",
        ctypes.c_int(AT_FDCWD),
        target.encode(),
        ctypes.c_uint(MOVE_MOUNT_F_EMPTY_PATH | MOVE_MOUNT_T_SYMLINKS),
    )
    _check(0 if result == 0 else -1, f"move_mount {target}")


def _parse_cgroupv2_path(client_pid: int) -> str | None:
    """Parse /proc/<pid>/cgroup for the cgroupv2 unified hierarchy line (0::...)."""
    try:
        text = open(f"/proc/{client_pid}/cgroup").read()
    except OSError:
        return None
    for line in text.splitlines():
        parts = line.split(":", 2)
        if len(parts) == 3 and parts[0] == "0" and parts[1] == "":
            return parts[2]
    return None


def _identity(client: ClientProcess, username: str | None, daemon_gid: int) -> tuple[int, int, list[int]]:
    """The uid, gid and supplementary groups of the process: those of the client, without the group of the daemon,
    which reaches its socket and so runs anything as anyone; or those of the user it names, from /etc/group."""
    if username is not None:
        pw = pwd.getpwnam(username)
        return pw.pw_uid, pw.pw_gid, os.getgrouplist(username, pw.pw_gid)

    gid = client.gid
    if gid == daemon_gid:
        try:
            gid = pwd.getpwuid(client.uid).pw_gid
        except KeyError:
            raise ClientProcessError(
                f"The client runs with the group of the daemon ({daemon_gid}) and its user {client.uid} has no other"
            ) from None
        if gid == daemon_gid:
            raise ClientProcessError(f"The user {client.uid} of the client has the group of the daemon ({daemon_gid})")
    groups = [group for group in client.groups if group != daemon_gid]
    return client.uid, gid, groups


def make_preexec_fn(
    *,
    tunnel_pid: int,
    tunnel_folder_path: Path,
    client: ClientProcess,
    daemon_gid: int,
    username: str | None = None,
    cwd: str | None = None,
    ambient_capabilities: frozenset[int] | None = None,
) -> tuple[Callable[[], None], Callable[[], None]]:
    """
    Return (preexec_fn, close_parent_fds).

    preexec_fn runs in the child after fork: it puts the process in the network of the tunnel, and makes it otherwise
    the same as its client, so that whatever sandboxes the client (a systemd unit) sandboxes the process too.
    close_parent_fds must be called in the parent after create_subprocess_exec (success or failure) to release the
    fds that were opened here as root to avoid a TOCTOU race.

    The child sequence is:
      1. setns() into the network namespace of the tunnel.
      2. setns() into the mount namespace of the client (ProtectSystem=, ReadWritePaths=, PrivateTmp=...), then
         unshare() a private one, slave of it, with the resolv.conf and nsswitch.conf of the tunnel on top.
      3. Best-effort: enter the client cgroup/UTS/IPC namespaces and join its cgroup (failures are logged, not fatal).
      4. The rlimits of the client.
      5. Drop from the bounding set what the client doesn't have in its own.
      6. PR_SET_KEEPCAPS so permitted caps survive setuid.
      7. setgroups/setgid/setuid: the identity of the client, or the user named.
      8. chdir() to cwd, with the rights of that user.
      9. The umask of the client.
     10. capset() and PR_CAP_AMBIENT_RAISE for the caps asked, within the bounding set.
     11. PR_SET_NO_NEW_PRIVS, as the client, and the seccomp filters of the client, last.
    """
    uid, gid, groups = _identity(client, username, daemon_gid)
    caps_to_use = sorted(
        cap
        for cap in (_CONTAINER_CAPS if ambient_capabilities is None else ambient_capabilities)
        if client.has_capability_in_bounding_set(cap)
    )
    cap_last_cap = int(Path("/proc/sys/kernel/cap_last_cap").read_text())
    caps_to_drop_from_bounding_set = [
        cap for cap in range(cap_last_cap + 1) if not client.has_capability_in_bounding_set(cap)
    ]
    # Without no_new_privs, installing a filter takes CAP_SYS_ADMIN, which the process doesn't keep: a client which
    # has filters without it is root, or was, and its process gets it, rather than to run unfiltered
    no_new_privs = client.no_new_privs or (bool(client.seccomp_filters) and CAP_SYS_ADMIN not in caps_to_use)

    # The BPF programs, made before the fork: the child only hands them to the kernel
    filter_buffers = [ctypes.create_string_buffer(program, len(program)) for program in client.seccomp_filters]
    filter_programs = [
        _SockFprog(len=len(buffer) // SOCK_FILTER_SIZE, filter=ctypes.cast(buffer, ctypes.c_void_p).value)
        for buffer in filter_buffers
    ]

    # Open namespace fds before the fork, as root, as the files of the tunnel, which the mount namespace of the client
    # may not show.
    net_fd = os.open(f"/proc/{tunnel_pid}/ns/net", os.O_RDONLY | os.O_CLOEXEC)
    client_mnt_fd = os.open(f"/proc/{client.pid}/ns/mnt", os.O_RDONLY | os.O_CLOEXEC)
    resolv_fd = os.open(tunnel_folder_path / "resolv.conf", os.O_PATH | os.O_CLOEXEC)
    nsswitch_fd = os.open(tunnel_folder_path / "nsswitch.conf", os.O_PATH | os.O_CLOEXEC)

    # Open client namespace fds and cgroup.procs before fork, as root.
    cgroup_ns_fd = os.open(f"/proc/{client.pid}/ns/cgroup", os.O_RDONLY | os.O_CLOEXEC)
    uts_fd = os.open(f"/proc/{client.pid}/ns/uts", os.O_RDONLY | os.O_CLOEXEC)
    ipc_fd = os.open(f"/proc/{client.pid}/ns/ipc", os.O_RDONLY | os.O_CLOEXEC)
    cgroup_procs_fd: int | None = None
    cg_path = _parse_cgroupv2_path(client.pid)
    if cg_path is not None:
        try:
            cgroup_procs_fd = os.open(f"/sys/fs/cgroup{cg_path}/cgroup.procs", os.O_WRONLY | os.O_CLOEXEC)
        except OSError as e:
            logger.warning("Could not open cgroup.procs for client pid {}: {}", client.pid, e)
    else:
        logger.warning("No cgroupv2 entry found for client pid {}; skipping cgroup membership", client.pid)

    _parent_fds: list[int] = [
        fd
        for fd in [net_fd, client_mnt_fd, resolv_fd, nsswitch_fd, cgroup_ns_fd, uts_fd, ipc_fd, cgroup_procs_fd]
        if fd is not None
    ]

    def _preexec() -> None:
        try:
            _prepare()
        except BaseException as error:
            # Python only tells the daemon that something failed: tell the client what, on the stderr of the process,
            # which it already is
            try:
                os.write(2, f"vpn-passthrough: could not start the process: {error}\n".encode())
            except OSError:
                pass
            raise

    def _prepare() -> None:
        # 1. Enter VPN network namespace
        _setns(net_fd, CLONE_NEWNET)

        # 2. Enter the mount namespace of the client, then one of its own, whose mounts don't go back to the client
        #    (nor to the host, if the client is in its namespace), while those of the client still come
        #    The files of the tunnel are mounts of the namespace of the daemon, which no other may bind: copy them
        #    first, detached, then mount the copies.
        resolv_tree_fd = _open_tree(resolv_fd)
        nsswitch_tree_fd = _open_tree(nsswitch_fd)
        _setns(client_mnt_fd, CLONE_NEWNS)
        os.unshare(CLONE_NEWNS)
        _mount(None, "/", MS_REC | MS_SLAVE)
        _move_mount(resolv_tree_fd, "/etc/resolv.conf")
        _move_mount(nsswitch_tree_fd, "/etc/nsswitch.conf")

        # 3. Best-effort: enter client namespaces and join cgroup (while still root).
        #    Failures here are non-fatal — the process still runs inside the VPN
        #    tunnel, just without the client's cgroup/UTS/IPC membership.
        for fd, nstype, name in [(cgroup_ns_fd, CLONE_NEWCGROUP, "cgroup"), (uts_fd, CLONE_NEWUTS, "UTS"), (ipc_fd, CLONE_NEWIPC, "IPC")]:
            try:
                _setns(fd, nstype)
            except OSError as e:
                logger.warning("Could not enter client {} namespace: {}", name, e)
        if cgroup_procs_fd is not None:
            try:
                os.write(cgroup_procs_fd, str(os.getpid()).encode())
            except OSError as e:
                logger.warning("Could not join client cgroup: {}", e)

        # 4. The rlimits of the client, while root may still raise them
        for rlimit, limits in client.rlimits.items():
            resource.setrlimit(rlimit, limits)

        # 5. Drop from the bounding set, with CAP_SETPCAP, still there
        for cap in caps_to_drop_from_bounding_set:
            _check(libc.prctl(PR_CAPBSET_DROP, cap, 0, 0, 0), f"prctl(PR_CAPBSET_DROP, {cap})")

        # 6. Keep capabilities across uid change
        if libc.prctl(PR_SET_KEEPCAPS, 1, 0, 0, 0) != 0:
            raise OSError(ctypes.get_errno(), "prctl(PR_SET_KEEPCAPS) failed")

        # 7. Drop privileges: the group too, or the process would keep the one of the daemon, whose socket would let it
        # run anything as anyone
        os.setgroups(groups)
        os.setgid(gid)
        os.setuid(uid)

        # 8. Change working directory as the target user, inside the namespace: before the caps are set, which, all
        # dropped, would keep even root out of the 0700 home of another user it runs from. Changing to another user
        # already cleared the effective caps, so that it is checked with their own rights.
        if cwd is not None:
            os.chdir(cwd)

        # 9. What the process creates, it creates as the client would
        os.umask(client.umask)

        # 10. Build a capability mask, of the caps asked which the bounding set has
        cap_mask = [0, 0]
        for cap in caps_to_use:
            cap_mask[cap // 32] |= 1 << (cap % 32)

        header = _CapHeader(version=_LINUX_CAPABILITY_VERSION_3, pid=0)
        data = (_CapData * 2)()
        for cap_set_index in range(2):
            data[cap_set_index].effective = cap_mask[cap_set_index]
            data[cap_set_index].permitted = cap_mask[cap_set_index]
            data[cap_set_index].inheritable = cap_mask[cap_set_index]

        if libc.capset(ctypes.byref(header), ctypes.byref(data)) != 0:
            raise OSError(ctypes.get_errno(), "capset failed")

        # Raise selected caps as ambient
        for cap in caps_to_use:
            if libc.prctl(PR_CAP_AMBIENT, PR_CAP_AMBIENT_RAISE, cap, 0, 0) != 0:
                raise OSError(ctypes.get_errno(), f"prctl(PR_CAP_AMBIENT_RAISE, {cap}) failed")

        # 11. Last, as they may forbid what comes before: no new privileges, then the filters of the client, in the
        # order it got them. Only exec follows.
        if no_new_privs:
            _check(libc.prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0), "prctl(PR_SET_NO_NEW_PRIVS)")
        for program in filter_programs:
            _check(libc.prctl(PR_SET_SECCOMP, SECCOMP_MODE_FILTER, ctypes.addressof(program), 0, 0), "prctl(PR_SET_SECCOMP)")


    def _close_parent_fds() -> None:
        while _parent_fds:
            try:
                os.close(_parent_fds.pop())
            except OSError:
                pass

    return _preexec, _close_parent_fds
