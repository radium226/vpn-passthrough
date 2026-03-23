import asyncio
import os
import signal
from pathlib import Path

import click

from radium226.vpn_passthrough.client import Client, ClientConfig
from radium226.vpn_passthrough.app.commands._helpers import pass_config_folder, lookup_or_create_tunnel


@click.command("run-process")
@click.option(
    "--kill-with",
    type=int,
    default=None,
    help="Signal to use when killing the process for restart (default: SIGTERM).",
)
@click.option(
    "--in-tunnel",
    "tunnel_name",
    default=None,
    help="Run the process inside the named tunnel. If omitted, a temporary tunnel is created and destroyed on exit.",
)
@click.option("--region-id", default=None, envvar="VPN_PASSTHROUGH_REGION_ID", help="VPN region ID for the temporary tunnel.")
@click.option("--backend-name", "backend_name", default=None, envvar="VPN_PASSTHROUGH_BACKEND", help="Backend name as configured in config file.")
@click.option("--configure-with", "configure_with", default=None, type=click.Path(), help="Script to run after port rebind and before process restart; receives tunnel context as JSON on stdin.")
@click.option("--kill-switch", "kill_switch", type=click.Choice(["yes", "no"]), default=None, help="Block all traffic that bypasses the VPN tunnel (default: yes). Only applies when creating a temporary tunnel.")
@click.argument("command", nargs=-1, required=True)
@pass_config_folder
def run_process(config_folder_path: Path | None, kill_with: int | None, tunnel_name: str | None, region_id: str | None, backend_name: str | None, configure_with: str | None, kill_switch: str | None, command: tuple[str, ...]) -> None:
    config = ClientConfig.load(config_folder_path)
    resolved_kill_switch = (kill_switch == "yes") if kill_switch is not None else True

    async def _run() -> None:
        loop = asyncio.get_running_loop()
        pid_future: asyncio.Future[int] = loop.create_future()

        async with Client.connect(config) as client:
            async with lookup_or_create_tunnel(client, tunnel_name, region_id, backend_name, kill_switch=resolved_kill_switch) as tunnel_info:
                async def handle_pid(pid: int) -> None:
                    if not pid_future.done():
                        pid_future.set_result(pid)

                def forward_signal(sig: signal.Signals) -> None:
                    async def _kill() -> None:
                        pid = await pid_future
                        await client.kill_process(pid, sig)
                    asyncio.create_task(_kill())

                for sig in (signal.SIGINT, signal.SIGTERM):
                    loop.add_signal_handler(sig, forward_signal, sig)

                try:
                    exit_code = await client.run_process(
                        command[0],
                        list(command[1:]),
                        fds=[os.dup(0), os.dup(1), os.dup(2)],
                        kill_with=kill_with,
                        tunnel_name=tunnel_info.name,
                        cwd=str(Path.cwd()),
                        gid=os.getgid(),
                        on_pid_received=handle_pid,
                        configure_with=configure_with,
                    )
                finally:
                    for sig in (signal.SIGINT, signal.SIGTERM):
                        loop.remove_signal_handler(sig)

        raise SystemExit(exit_code)

    asyncio.run(_run())
