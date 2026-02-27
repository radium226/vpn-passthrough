import os
import pwd
import ctypes
from collections.abc import Callable

# Namespace constants
CLONE_NEWNS  = 0x00020000
CLONE_NEWNET = 0x40000000

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


def make_preexec_fn(username: str, ns_pid: int, cwd: str | None = None) -> Callable[[], None]:
    """
    Return a preexec_fn that enters namespaces and drops privileges.

    The sequence is:
      1. setns() into mount and network namespaces.
      2. PR_SET_KEEPCAPS so permitted caps survive setuid.
      3. setgid/setuid to drop to the real user.
      4. capset() to restore all permitted caps in effective+inheritable.
      5. PR_CAP_AMBIENT_RAISE for each permitted cap (inherited by exec).

    Namespace fds are opened here, in the parent, to:
      - Avoid a TOCTOU race if ns_pid exits before the child calls setns().
      - Ensure we can still read /proc/<ns_pid>/ns/* as root.
    """
    pw  = pwd.getpwnam(username)
    uid = pw.pw_uid
    gid = pw.pw_gid

    # Open namespace fds before the fork, as root.
    mnt_fd = os.open(f"/proc/{ns_pid}/ns/mnt", os.O_RDONLY)
    net_fd = os.open(f"/proc/{ns_pid}/ns/net", os.O_RDONLY)

    def _preexec():
        # 1. Enter mount namespace
        _setns(mnt_fd, CLONE_NEWNS)
        os.close(mnt_fd)

        # Enter network namespace
        _setns(net_fd, CLONE_NEWNET)
        os.close(net_fd)

        # 2. Keep capabilities across uid change
        if libc.prctl(PR_SET_KEEPCAPS, 1, 0, 0, 0) != 0:
            raise OSError(ctypes.get_errno(), "prctl(PR_SET_KEEPCAPS) failed")

        # 3. Drop privileges
        os.initgroups(username, gid)
        os.setuid(uid)

        # 4. Build a capability mask matching default Docker/Podman containers
        cap_mask = [0, 0]
        for cap in _CONTAINER_CAPS:
            cap_mask[cap // 32] |= 1 << (cap % 32)

        header = _CapHeader(version=_LINUX_CAPABILITY_VERSION_3, pid=0)
        data = (_CapData * 2)()
        for i in range(2):
            data[i].effective = cap_mask[i]
            data[i].permitted = cap_mask[i]
            data[i].inheritable = cap_mask[i]

        if libc.capset(ctypes.byref(header), ctypes.byref(data)) != 0:
            raise OSError(ctypes.get_errno(), "capset failed")

        # 5. Raise container caps as ambient
        for cap in _CONTAINER_CAPS:
            if libc.prctl(PR_CAP_AMBIENT, PR_CAP_AMBIENT_RAISE, cap, 0, 0) != 0:
                raise OSError(ctypes.get_errno(), f"prctl(PR_CAP_AMBIENT_RAISE, {cap}) failed")

        # 6. Change working directory as the target user, inside the namespace
        if cwd is not None:
            os.chdir(cwd)

    return _preexec
