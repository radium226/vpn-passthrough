import os
import pwd
import ctypes
from collections.abc import Callable

from loguru import logger

# Namespace constants
CLONE_NEWNS     = 0x00020000
CLONE_NEWNET    = 0x40000000
CLONE_NEWUTS    = 0x04000000
CLONE_NEWIPC    = 0x08000000
CLONE_NEWCGROUP = 0x02000000

# Capability constants
PR_SET_KEEPCAPS = 8
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


class _CapHeader(ctypes.Structure):
    _fields_ = [("version", ctypes.c_uint32), ("pid", ctypes.c_int)]


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


def make_preexec_fn(username: str, ns_pid: int, cwd: str | None = None, client_pid: int | None = None) -> tuple[Callable[[], None], Callable[[], None]]:
    """
    Return (preexec_fn, close_parent_fds).

    preexec_fn runs in the child after fork and enters namespaces + drops
    privileges. close_parent_fds must be called in the parent after
    create_subprocess_exec (success or failure) to release the fds that were
    opened here as root to avoid a TOCTOU race.

    The child sequence is:
      1. setns() into mount and network namespaces.
      2. If client_pid: best-effort enter client cgroup/UTS/IPC namespaces
         and join cgroup (failures are logged, not fatal).
      3. PR_SET_KEEPCAPS so permitted caps survive setuid.
      4. setgid/setuid to drop to the real user.
      5. capset() to restore all permitted caps in effective+inheritable.
      6. PR_CAP_AMBIENT_RAISE for each permitted cap (inherited by exec).
    """
    pw  = pwd.getpwnam(username)
    uid = pw.pw_uid
    gid = pw.pw_gid

    # Open namespace fds before the fork, as root.
    mnt_fd = os.open(f"/proc/{ns_pid}/ns/mnt", os.O_RDONLY)
    net_fd = os.open(f"/proc/{ns_pid}/ns/net", os.O_RDONLY)

    # Open client namespace fds and cgroup.procs before fork, as root.
    cgroup_ns_fd: int | None = None
    uts_fd: int | None = None
    ipc_fd: int | None = None
    cgroup_procs_fd: int | None = None
    if client_pid is not None:
        cgroup_ns_fd = os.open(f"/proc/{client_pid}/ns/cgroup", os.O_RDONLY)
        uts_fd       = os.open(f"/proc/{client_pid}/ns/uts",    os.O_RDONLY)
        ipc_fd       = os.open(f"/proc/{client_pid}/ns/ipc",    os.O_RDONLY)
        cg_path = _parse_cgroupv2_path(client_pid)
        if cg_path is not None:
            try:
                cgroup_procs_fd = os.open(f"/sys/fs/cgroup{cg_path}/cgroup.procs", os.O_WRONLY)
            except OSError as e:
                logger.warning("Could not open cgroup.procs for client pid {}: {}", client_pid, e)
        else:
            logger.warning("No cgroupv2 entry found for client pid {}; skipping cgroup membership", client_pid)

    _parent_fds: list[int] = [
        fd for fd in [mnt_fd, net_fd, cgroup_ns_fd, uts_fd, ipc_fd, cgroup_procs_fd]
        if fd is not None
    ]

    def _preexec() -> None:
        # 1. Enter VPN mount namespace
        _setns(mnt_fd, CLONE_NEWNS)
        os.close(mnt_fd)

        # Enter VPN network namespace
        _setns(net_fd, CLONE_NEWNET)
        os.close(net_fd)

        # 2. Best-effort: enter client namespaces and join cgroup (while still root).
        #    Failures here are non-fatal — the process still runs inside the VPN
        #    tunnel, just without the client's cgroup/UTS/IPC membership.
        if cgroup_ns_fd is not None:
            try:
                _setns(cgroup_ns_fd, CLONE_NEWCGROUP)
            except OSError as e:
                logger.warning("Could not enter client cgroup namespace: {}", e)
            os.close(cgroup_ns_fd)
        if uts_fd is not None:
            try:
                _setns(uts_fd, CLONE_NEWUTS)
            except OSError as e:
                logger.warning("Could not enter client UTS namespace: {}", e)
            os.close(uts_fd)
        if ipc_fd is not None:
            try:
                _setns(ipc_fd, CLONE_NEWIPC)
            except OSError as e:
                logger.warning("Could not enter client IPC namespace: {}", e)
            os.close(ipc_fd)
        if cgroup_procs_fd is not None:
            try:
                os.write(cgroup_procs_fd, str(os.getpid()).encode())
            except OSError as e:
                logger.warning("Could not join client cgroup: {}", e)
            os.close(cgroup_procs_fd)

        # 3. Keep capabilities across uid change
        if libc.prctl(PR_SET_KEEPCAPS, 1, 0, 0, 0) != 0:
            raise OSError(ctypes.get_errno(), "prctl(PR_SET_KEEPCAPS) failed")

        # 4. Drop privileges
        os.initgroups(username, gid)
        os.setuid(uid)

        # 5. Build a capability mask matching default Docker/Podman containers
        cap_mask = [0, 0]
        for cap in _CONTAINER_CAPS:
            cap_mask[cap // 32] |= 1 << (cap % 32)

        header = _CapHeader(version=_LINUX_CAPABILITY_VERSION_3, pid=0)
        data = (_CapData * 2)()
        for cap_set_index in range(2):
            data[cap_set_index].effective = cap_mask[cap_set_index]
            data[cap_set_index].permitted = cap_mask[cap_set_index]
            data[cap_set_index].inheritable = cap_mask[cap_set_index]

        if libc.capset(ctypes.byref(header), ctypes.byref(data)) != 0:
            raise OSError(ctypes.get_errno(), "capset failed")

        # 6. Raise container caps as ambient
        for cap in _CONTAINER_CAPS:
            if libc.prctl(PR_CAP_AMBIENT, PR_CAP_AMBIENT_RAISE, cap, 0, 0) != 0:
                raise OSError(ctypes.get_errno(), f"prctl(PR_CAP_AMBIENT_RAISE, {cap}) failed")

        # 7. Change working directory as the target user, inside the namespace
        if cwd is not None:
            os.chdir(cwd)

    def _close_parent_fds() -> None:
        while _parent_fds:
            try:
                os.close(_parent_fds.pop())
            except OSError:
                pass

    return _preexec, _close_parent_fds
