import asyncio
import os
import signal
import uuid
from pathlib import Path
from typing import Never

import pytest

from radium226.vpn_passthrough.ipc.ipc import open_client, open_server
from radium226.vpn_passthrough.ipc.protocol import RequestHandler, ResponseHandler

from radium226.vpn_passthrough.server.service import Service
from radium226.vpn_passthrough.messages import (
    CODEC,
    CommandNotFound,
    KillProcess,
    ProcessKilled,
    ProcessStarted,
    ProcessTerminated,
    RunProcess,
    Tunnel,
)


@pytest.fixture
def socket_path(tmp_path: Path) -> Path:
    return tmp_path / "test.socket"


@pytest.fixture
def service_handlers(tmp_path: Path) -> list[RequestHandler]:
    service = Service(tmp_path)
    return [
        RequestHandler(request_type=RunProcess, on_request=service.handle_run_process),
        RequestHandler(request_type=KillProcess, on_request=service.handle_kill_process),
    ]


async def _async_noop(*_args: object) -> None:
    pass


@pytest.mark.asyncio
async def test_exec_returns_exit_code(socket_path: Path, service_handlers: list[RequestHandler]):
    async with open_server(socket_path, CODEC, handlers=service_handlers):
        async with open_client(socket_path, CODEC) as client:
            stdin_r, stdin_w = os.pipe()
            stdout_r, stdout_w = os.pipe()
            stderr_r, stderr_w = os.pipe()

            result_exit_code: int | None = None

            async def on_response(response: ProcessTerminated | CommandNotFound, fds: list[int]) -> None:
                nonlocal result_exit_code
                match response:
                    case ProcessTerminated(exit_code=ec):
                        result_exit_code = ec

            await client.request(
                RunProcess(id=str(uuid.uuid4()), command="sh", args=["-c", "exit 42"]),
                fds=[stdin_r, stdout_w, stderr_w],
                handler=ResponseHandler[ProcessStarted, ProcessTerminated | CommandNotFound](
                    on_response=on_response,
                ),
            )

            os.close(stdin_w)
            os.close(stdout_r)
            os.close(stderr_r)

            assert result_exit_code == 42


@pytest.mark.asyncio
async def test_exec_captures_stdout(socket_path: Path, service_handlers: list[RequestHandler]):
    async with open_server(socket_path, CODEC, handlers=service_handlers):
        async with open_client(socket_path, CODEC) as client:
            stdin_r, stdin_w = os.pipe()
            stdout_r, stdout_w = os.pipe()
            stderr_r, stderr_w = os.pipe()

            result_exit_code: int | None = None

            async def on_response(response: ProcessTerminated | CommandNotFound, fds: list[int]) -> None:
                nonlocal result_exit_code
                match response:
                    case ProcessTerminated(exit_code=ec):
                        result_exit_code = ec

            await client.request(
                RunProcess(id=str(uuid.uuid4()), command="echo", args=["hello world"]),
                fds=[stdin_r, stdout_w, stderr_w],
                handler=ResponseHandler[ProcessStarted, ProcessTerminated | CommandNotFound](
                    on_response=on_response,
                ),
            )

            os.close(stdin_w)
            os.close(stderr_r)

            output = os.read(stdout_r, 4096)
            os.close(stdout_r)

            assert result_exit_code == 0
            assert output == b"hello world\n"


@pytest.mark.asyncio
async def test_exec_emits_process_started(socket_path: Path, service_handlers: list[RequestHandler]):
    async with open_server(socket_path, CODEC, handlers=service_handlers):
        async with open_client(socket_path, CODEC) as client:
            stdin_r, stdin_w = os.pipe()
            stdout_r, stdout_w = os.pipe()
            stderr_r, stderr_w = os.pipe()

            started_pid: int | None = None

            async def on_event(event: ProcessStarted, fds: list[int]) -> None:
                nonlocal started_pid
                started_pid = event.pid

            await client.request(
                RunProcess(id=str(uuid.uuid4()), command="true"),
                fds=[stdin_r, stdout_w, stderr_w],
                handler=ResponseHandler[ProcessStarted, ProcessTerminated | CommandNotFound](
                    on_event=on_event,
                ),
            )

            os.close(stdin_w)
            os.close(stdout_r)
            os.close(stderr_r)

            assert started_pid is not None
            assert started_pid > 0


@pytest.mark.asyncio
async def test_kill_process(socket_path: Path, service_handlers: list[RequestHandler]):
    async with open_server(socket_path, CODEC, handlers=service_handlers):
        async with open_client(socket_path, CODEC) as client:
            stdin_r, stdin_w = os.pipe()
            stdout_r, stdout_w = os.pipe()
            stderr_r, stderr_w = os.pipe()

            started_pid: int | None = None
            result_exit_code: int | None = None

            async def on_event(event: ProcessStarted, fds: list[int]) -> None:
                nonlocal started_pid
                started_pid = event.pid

                # Fire-and-forget kill (can't await from receive loop callback)
                asyncio.create_task(
                    client.request(
                        KillProcess(id=str(uuid.uuid4()), pid=event.pid, signal=signal.SIGTERM),
                        handler=ResponseHandler[Never, ProcessKilled](
                            on_response=_async_noop,
                        ),
                    )
                )

            async def on_response(response: ProcessTerminated | CommandNotFound, fds: list[int]) -> None:
                nonlocal result_exit_code
                match response:
                    case ProcessTerminated(exit_code=ec):
                        result_exit_code = ec

            await client.request(
                RunProcess(id=str(uuid.uuid4()), command="sleep", args=["60"]),
                fds=[stdin_r, stdout_w, stderr_w],
                handler=ResponseHandler[ProcessStarted, ProcessTerminated | CommandNotFound](
                    on_event=on_event,
                    on_response=on_response,
                ),
            )

            os.close(stdin_w)
            os.close(stdout_r)
            os.close(stderr_r)

            assert started_pid is not None
            assert result_exit_code is not None


@pytest.mark.asyncio
@pytest.mark.skipif(os.getuid() != 0, reason="requires root (CAP_NET_ADMIN)")
async def test_run_process_in_tunnel(socket_path: Path, service_handlers: list[RequestHandler]):
    async with open_server(socket_path, CODEC, handlers=service_handlers):
        async with open_client(socket_path, CODEC) as client:
            stdin_r, stdin_w = os.pipe()
            stdout_r, stdout_w = os.pipe()
            stderr_r, stderr_w = os.pipe()

            result_exit_code: int | None = None
            output = b""

            async def on_response(response: ProcessTerminated | CommandNotFound, fds: list[int]) -> None:
                nonlocal result_exit_code
                match response:
                    case ProcessTerminated(exit_code=ec):
                        result_exit_code = ec

            await client.request(
                RunProcess(
                    id=str(uuid.uuid4()),
                    command="ip",
                    args=["route"],
                    in_tunnel=Tunnel(name="test-vpn-ns"),
                ),
                fds=[stdin_r, stdout_w, stderr_w],
                handler=ResponseHandler[ProcessStarted, ProcessTerminated | CommandNotFound](
                    on_response=on_response,
                ),
            )

            os.close(stdin_w)
            os.close(stderr_r)

            output = os.read(stdout_r, 4096)
            os.close(stdout_r)

            assert result_exit_code == 0
            # The default route inside the netns points to the veth address (10.200.x.x)
            assert b"default via 10.200." in output


@pytest.mark.asyncio
@pytest.mark.skipif(os.getuid() != 0, reason="requires root (CAP_NET_ADMIN)")
async def test_run_process_in_tunnel_can_curl(socket_path: Path, service_handlers: list[RequestHandler]):
    async with open_server(socket_path, CODEC, handlers=service_handlers):
        async with open_client(socket_path, CODEC) as client:
            stdin_r, stdin_w = os.pipe()
            stdout_r, stdout_w = os.pipe()
            stderr_r, stderr_w = os.pipe()

            result_exit_code: int | None = None

            async def on_response(response: ProcessTerminated | CommandNotFound, fds: list[int]) -> None:
                nonlocal result_exit_code
                match response:
                    case ProcessTerminated(exit_code=ec):
                        result_exit_code = ec

            await client.request(
                RunProcess(
                    id=str(uuid.uuid4()),
                    command="curl",
                    args=["--fail", "--max-time", "10", "https://ipinfo.io/ip"],
                    in_tunnel=Tunnel(name="test-curl-ns"),
                ),
                fds=[stdin_r, stdout_w, stderr_w],
                handler=ResponseHandler[ProcessStarted, ProcessTerminated | CommandNotFound](
                    on_response=on_response,
                ),
            )

            # Close the fds we passed to the server — the test still holds its
            # copies, keeping the write-end of stdout_w open and blocking os.read.
            os.close(stdin_r)
            os.close(stdout_w)
            os.close(stderr_w)

            os.close(stdin_w)

            stdout = os.read(stdout_r, 4096)
            os.close(stdout_r)

            print(f"curl output: {stdout.decode()!r}")

            stderr = os.read(stderr_r, 4096)
            os.close(stderr_r)
            print(f"curl stderr: {stderr.decode()!r}")

            assert result_exit_code == 0
            # Response should be a valid IP address
            assert len(stdout.strip()) > 0


@pytest.mark.asyncio
async def test_command_not_found(socket_path: Path, service_handlers: list[RequestHandler]):
    async with open_server(socket_path, CODEC, handlers=service_handlers):
        async with open_client(socket_path, CODEC) as client:
            stdin_r, stdin_w = os.pipe()
            stdout_r, stdout_w = os.pipe()
            stderr_r, stderr_w = os.pipe()

            not_found_command: str | None = None

            async def on_response(response: ProcessTerminated | CommandNotFound, fds: list[int]) -> None:
                nonlocal not_found_command
                match response:
                    case CommandNotFound(command=cmd):
                        not_found_command = cmd

            await client.request(
                RunProcess(id=str(uuid.uuid4()), command="nonexistent_command_xyz_123"),
                fds=[stdin_r, stdout_w, stderr_w],
                handler=ResponseHandler[ProcessStarted, ProcessTerminated | CommandNotFound](
                    on_response=on_response,
                ),
            )

            os.close(stdin_w)
            os.close(stdout_r)
            os.close(stderr_r)

            assert not_found_command == "nonexistent_command_xyz_123"
