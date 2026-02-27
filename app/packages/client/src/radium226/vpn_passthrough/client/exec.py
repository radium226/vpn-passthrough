import asyncio
import os
import signal
import uuid
from pathlib import Path
from typing import Never

from loguru import logger

from radium226.vpn_passthrough.ipc.ipc import open_client
from radium226.vpn_passthrough.ipc.protocol import ResponseHandler

from radium226.vpn_passthrough.messages import (
    CODEC,
    CommandNotFound,
    KillProcess,
    ProcessKilled,
    ProcessRestarted,
    ProcessStarted,
    ProcessTerminated,
    RunProcess,
    Tunnel,
)


async def _async_noop(*_args: object) -> None:
    pass


async def exec_(socket_file_path: Path, command: tuple[str, ...], restart_every: float | None = None, kill_with: int | None = None, in_tunnel: Tunnel | None = None) -> None:
    async with open_client(socket_file_path, CODEC) as client:
        stdin_fd = os.dup(0)
        stdout_fd = os.dup(1)
        stderr_fd = os.dup(2)

        pid: int | None = None
        pending_signals: list[signal.Signals] = []
        result_exit_code = 0
        loop = asyncio.get_running_loop()

        def _send_kill(target_pid: int, sig: signal.Signals) -> None:
            asyncio.create_task(
                client.request(
                    KillProcess(id=str(uuid.uuid4()), pid=target_pid, signal=sig),
                    handler=ResponseHandler[Never, ProcessKilled](
                        on_response=_async_noop,
                    ),
                    fds=[],
                )
            )

        def forward_signal(sig: signal.Signals) -> None:
            if pid is not None:
                _send_kill(pid, sig)
            else:
                pending_signals.append(sig)

        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, forward_signal, sig)

        async def on_event(event: ProcessStarted | ProcessRestarted, fds: list[int]) -> None:
            nonlocal pid
            pid = event.pid
            match event:
                case ProcessRestarted(pid=new_pid):
                    logger.debug("Process restarted (pid={})", new_pid)
            for queued_sig in pending_signals:
                _send_kill(pid, queued_sig)
            pending_signals.clear()

        async def on_response(response: ProcessTerminated | CommandNotFound, fds: list[int]) -> None:
            nonlocal result_exit_code
            match response:
                case ProcessTerminated(exit_code=exit_code):
                    result_exit_code = exit_code
                case CommandNotFound():
                    result_exit_code = 127

        try:
            await client.request(
                RunProcess(id=str(uuid.uuid4()), command=command[0], args=list(command[1:]), restart_every=restart_every, kill_with=kill_with, in_tunnel=in_tunnel),
                handler=ResponseHandler[ProcessStarted | ProcessRestarted, ProcessTerminated | CommandNotFound](
                    on_response=on_response,
                    on_event=on_event,
                ),
                fds=[stdin_fd, stdout_fd, stderr_fd],
            )
        finally:
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.remove_signal_handler(sig)

        raise SystemExit(result_exit_code)
