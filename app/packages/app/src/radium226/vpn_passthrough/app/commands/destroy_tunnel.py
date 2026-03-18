import asyncio
from pathlib import Path

import click

from radium226.vpn_passthrough.client import Client, ClientConfig
from radium226.vpn_passthrough.app.commands._helpers import pass_config_folder


@click.command("destroy-tunnel")
@click.argument("name")
@pass_config_folder
def destroy_tunnel(config_folder_path: Path | None, name: str) -> None:
    config = ClientConfig.load(config_folder_path)

    async def _run() -> None:
        async with Client.connect(config) as client:
            await client.destroy_tunnel(name)

    asyncio.run(_run())
