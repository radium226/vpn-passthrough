import asyncio
import fcntl
import os
import pty
import signal
import struct
import termios
import tty
from pathlib import Path

import click

from radium226.vpn_passthrough.client import Client, ClientConfig
from radium226.vpn_passthrough.app.commands._helpers import pass_config_folder, lookup_or_create_tunnel


async def _proxy_pty(master_fd: int) -> None:
    """Forward bytes between the real terminal and the PTY master until cancelled or an I/O error."""
    loop = asyncio.get_running_loop()
    done: asyncio.Future[None] = loop.create_future()

    def _read_stdin() -> None:
        try:
            data = os.read(0, 4096)
            if data:
                os.write(master_fd, data)
        except OSError:
            if not done.done():
                done.set_result(None)

    def _read_master() -> None:
        try:
            data = os.read(master_fd, 4096)
            if data:
                os.write(1, data)
        except OSError:
            if not done.done():
                done.set_result(None)

    loop.add_reader(0, _read_stdin)
    loop.add_reader(master_fd, _read_master)
    try:
        await done
    except asyncio.CancelledError:
        pass
    finally:
        loop.remove_reader(0)
        loop.remove_reader(master_fd)


@click.command("debug-tunnel")
@click.option(
    "--in-tunnel",
    "tunnel_name",
    default=None,
    help="Run bash inside the named tunnel. If omitted, a temporary tunnel is created and destroyed on exit.",
)
@click.option("--region-id", default=None, envvar="VPN_PASSTHROUGH_REGION_ID", help="VPN region ID for the temporary tunnel.")
@click.option("--backend-name", "backend_name", default=None, envvar="VPN_PASSTHROUGH_BACKEND", help="Backend name as configured in config file.")
@pass_config_folder
def debug_tunnel(config_folder_path: Path | None, tunnel_name: str | None, region_id: str | None, backend_name: str | None) -> None:
    config = ClientConfig.load(config_folder_path)

    async def _run() -> None:
        loop = asyncio.get_running_loop()

        master_fd, slave_fd = pty.openpty()

        # Mirror the real terminal size into the PTY slave
        try:
            cols, rows = os.get_terminal_size(0)
            fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        except OSError:
            pass

        def _sync_winsize() -> None:
            try:
                cols, rows = os.get_terminal_size(0)
                fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
            except OSError:
                pass

        loop.add_signal_handler(signal.SIGWINCH, _sync_winsize)

        # Raw mode: every keystroke goes straight to the PTY master
        is_tty = os.isatty(0)
        old_settings = termios.tcgetattr(0) if is_tty else None
        if is_tty:
            tty.setraw(0)

        proxy_task: asyncio.Task[None] | None = None
        exit_code = 1
        try:
            async with Client.connect(config) as client:
                async with lookup_or_create_tunnel(client, tunnel_name, region_id, backend_name) as tunnel_info:
                    proxy_task = asyncio.create_task(_proxy_pty(master_fd))
                    exit_code = await client.run_process(
                        "bash",
                        [],
                        # All three stdio fds point to the PTY slave; SCM_RIGHTS
                        # dups them independently in the server process.
                        fds=[slave_fd, slave_fd, slave_fd],
                        tunnel_name=tunnel_info.name,
                        cwd=str(Path.cwd()),
                        # Do NOT drop to user's uid/gid: setuid() clears all capability
                        # sets, and even if ping's file capabilities can restore
                        # CAP_NET_RAW via the bounding set, a restricted bounding set
                        # (e.g. from a systemd service) will silently break it.
                        # Running as root inside the isolated network namespace is safe
                        # because the tunnel provides full network-stack isolation.
                    )
        finally:
            if proxy_task is not None:
                proxy_task.cancel()
                try:
                    await proxy_task
                except asyncio.CancelledError:
                    pass
            loop.remove_signal_handler(signal.SIGWINCH)
            os.close(slave_fd)
            os.close(master_fd)
            if is_tty and old_settings is not None:
                termios.tcsetattr(0, termios.TCSADRAIN, old_settings)

        raise SystemExit(exit_code)

    asyncio.run(_run())
