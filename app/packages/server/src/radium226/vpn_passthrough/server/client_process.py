"""What the process a client runs in a tunnel copies of the client: whatever a systemd unit (or anything else) set on
it, so that a unit whose ExecStart is `vpn-passthrough run-process` hardens the process, not only the client.

All of it is read by the daemon, as root, from /proc and the kernel, never from what the client says.
"""

import ctypes
import os
import resource
from dataclasses import dataclass

from loguru import logger

_libc = ctypes.CDLL("libc.so.6", use_errno=True)
_libc.ptrace.argtypes = [ctypes.c_long, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p]
_libc.ptrace.restype = ctypes.c_long

_PTRACE_DETACH = 17
_PTRACE_SEIZE = 0x4206
_PTRACE_INTERRUPT = 0x4207
_PTRACE_SECCOMP_GET_FILTER = 0x420C
_WALL = 0x40000000

_SECCOMP_MODE_FILTER = 2

# Of struct sock_filter: u16 code, u8 jt, u8 jf, u32 k
SOCK_FILTER_SIZE = 8

RLIMITS = [getattr(resource, name) for name in dir(resource) if name.startswith("RLIMIT_")]


class ClientProcessError(Exception):
    """What the process would have to run without, which it rather doesn't run at all."""


@dataclass(frozen=True)
class ClientProcess:
    pid: int
    uid: int
    gid: int
    groups: tuple[int, ...]
    umask: int
    no_new_privs: bool
    capability_bounding_set: int
    rlimits: dict[int, tuple[int, int]]
    # Each one its BPF program, as an array of struct sock_filter, from the first installed to the last
    seccomp_filters: tuple[bytes, ...]

    def has_capability_in_bounding_set(self, capability: int) -> bool:
        return bool(self.capability_bounding_set >> capability & 1)


def _status(pid: int) -> dict[str, str]:
    with open(f"/proc/{pid}/status") as file:
        return {key: value.strip() for key, _, value in (line.partition(":") for line in file)}


def _ptrace(request: int, pid: int, addr: int | None, data: ctypes.c_void_p | int | None) -> int:
    result = _libc.ptrace(request, pid, addr, data)
    if result == -1:
        errno = ctypes.get_errno()
        raise OSError(errno, os.strerror(errno), f"ptrace({request:#x})")
    return result


def read_seccomp_filters(pid: int) -> tuple[bytes, ...]:
    """The seccomp filters of the process, which only a tracer may read: attach, stop it, read, and let it go. The
    kernel lists them from the first installed. All the calls happen in the thread of the caller, which ptrace ties the
    tracee to: run it in a thread of its own."""
    _ptrace(_PTRACE_SEIZE, pid, None, None)
    try:
        _ptrace(_PTRACE_INTERRUPT, pid, None, None)
        os.waitpid(pid, _WALL)
        filters: list[bytes] = []
        while True:
            try:
                length = _ptrace(_PTRACE_SECCOMP_GET_FILTER, pid, len(filters), None)
            except OSError as error:
                # ENOENT: past the last installed
                if error.errno == 2:
                    break
                raise
            buffer = ctypes.create_string_buffer(length * SOCK_FILTER_SIZE)
            _ptrace(_PTRACE_SECCOMP_GET_FILTER, pid, len(filters), ctypes.cast(buffer, ctypes.c_void_p))
            filters.append(buffer.raw)
    finally:
        _ptrace(_PTRACE_DETACH, pid, None, None)
    return tuple(filters)


def read_client_process(pid: int) -> ClientProcess:
    """Everything the process copies of the client, which must still be there: it waits for the answer."""
    status = _status(pid)
    seccomp_mode = int(status.get("Seccomp", "0"))
    if seccomp_mode not in (0, _SECCOMP_MODE_FILTER):
        raise ClientProcessError(f"The client {pid} is in the strict mode of seccomp, which no process may copy")
    seccomp_filters: tuple[bytes, ...] = ()
    if seccomp_mode == _SECCOMP_MODE_FILTER:
        try:
            seccomp_filters = read_seccomp_filters(pid)
        except OSError as error:
            raise ClientProcessError(f"Could not read the seccomp filters of the client {pid}: {error}") from error
        logger.debug("Read {} seccomp filters of the client {}", len(seccomp_filters), pid)

    return ClientProcess(
        pid=pid,
        # The real ones
        uid=int(status["Uid"].split()[0]),
        gid=int(status["Gid"].split()[0]),
        groups=tuple(int(group) for group in status["Groups"].split()),
        umask=int(status["Umask"], 8),
        no_new_privs=status["NoNewPrivs"] == "1",
        capability_bounding_set=int(status["CapBnd"], 16),
        rlimits={rlimit: resource.prlimit(pid, rlimit) for rlimit in RLIMITS},
        seccomp_filters=seccomp_filters,
    )
