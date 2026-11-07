import ctypes
import os
import resource
import struct
import subprocess
import sys
from collections.abc import Iterator

import pytest

from radium226.vpn_passthrough.server.client_process import ClientProcessError, read_client_process

# A filter which allows everything: BPF_RET | BPF_K, SECCOMP_RET_ALLOW
ALLOW_ALL = struct.pack("HBBI", 0x06, 0, 0, 0x7FFF0000)
# One which allows everything too, told apart by its jumps: BPF_JMP | BPF_JA 0, then the same
JUMP_THEN_ALLOW = struct.pack("HBBI", 0x05, 0, 0, 0) + ALLOW_ALL

PR_SET_NO_NEW_PRIVS = 38
PR_SET_SECCOMP = 22
SECCOMP_MODE_FILTER = 2


class _SockFprog(ctypes.Structure):
    _fields_ = [("len", ctypes.c_ushort), ("filter", ctypes.c_void_p)]


def _sandbox() -> None:
    """In the client: what a systemd unit would do."""
    libc = ctypes.CDLL("libc.so.6", use_errno=True)
    os.umask(0o027)
    resource.setrlimit(resource.RLIMIT_NOFILE, (512, 1024))
    libc.prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0)
    for program in (ALLOW_ALL, JUMP_THEN_ALLOW):
        buffer = ctypes.create_string_buffer(program, len(program))
        fprog = _SockFprog(len=len(program) // 8, filter=ctypes.cast(buffer, ctypes.c_void_p).value)
        assert libc.prctl(PR_SET_SECCOMP, SECCOMP_MODE_FILTER, ctypes.byref(fprog), 0, 0) == 0


@pytest.fixture
def client() -> Iterator[subprocess.Popen[bytes]]:
    process = subprocess.Popen(
        [sys.executable, "-c", "import sys; sys.stdout.write('ready\\n'); sys.stdout.flush(); sys.stdin.read()"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        preexec_fn=_sandbox,
    )
    assert process.stdout is not None and process.stdout.readline() == b"ready\n"
    yield process
    process.kill()
    process.wait()


def test_a_client_whose_filters_cant_be_read_is_refused(client: subprocess.Popen[bytes]) -> None:
    if os.geteuid() == 0:
        pytest.skip("As root, the filters are read too: see the test below")
    with pytest.raises(ClientProcessError, match="seccomp filters"):
        read_client_process(client.pid)


@pytest.mark.skipif(os.geteuid() != 0, reason="Reading seccomp filters takes CAP_SYS_ADMIN")
def test_the_process_copies_the_seccomp_filters_in_order(client: subprocess.Popen[bytes]) -> None:
    state = read_client_process(client.pid)

    assert state.umask == 0o027
    assert state.rlimits[resource.RLIMIT_NOFILE] == (512, 1024)
    assert state.no_new_privs
    assert state.seccomp_filters == (ALLOW_ALL, JUMP_THEN_ALLOW)
    # Still running, once let go
    assert client.poll() is None


def test_a_client_without_filters_is_read_without_ptrace() -> None:
    state = read_client_process(os.getpid())

    assert (state.uid, state.gid) == (os.getuid(), os.getgid())
    assert set(state.groups) == set(os.getgroups())
    assert state.umask == (umask := os.umask(0)) and os.umask(umask) == 0
    assert state.seccomp_filters == ()
