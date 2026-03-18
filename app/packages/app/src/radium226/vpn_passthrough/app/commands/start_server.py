import asyncio
from pathlib import Path

import click

from radium226.vpn_passthrough.server import Server, ServerConfig
from radium226.vpn_passthrough.messages import TunnelInfo
from radium226.vpn_passthrough.app.systemd import sd_notify
from radium226.vpn_passthrough.app.commands._helpers import pass_config_folder


def _on_tunnels_changed(tunnels: list[TunnelInfo]) -> None:
    tunnel_count = len(tunnels)
    if tunnel_count == 0:
        status = "No tunnel created"
    else:
        parts = [tunnel.region_id or tunnel.name for tunnel in tunnels]
        word = "tunnel" if tunnel_count == 1 else "tunnels"
        status = f"{tunnel_count} {word} created ({', '.join(parts)})"
    sd_notify(f"STATUS={status}")


@click.command("start-server")
@pass_config_folder
def start_server(config_folder_path: Path | None) -> None:
    config = ServerConfig.load(config_folder_path)

    async def _run() -> None:
        async with Server.listen(
            config,
            on_tunnels_changed=_on_tunnels_changed,
        ) as server:
            sd_notify("READY=1")
            _on_tunnels_changed([])
            await server.wait_forever()

    asyncio.run(_run())
