import asyncio
from pathlib import Path

import click

from radium226.vpn_passthrough.client import Client, ClientConfig
from radium226.vpn_passthrough.app.commands._helpers import pass_config_folder


@click.command("destroy-tunnel")
@click.argument("name")
@click.option("--wait", is_flag=True, default=False, help="Wait for running processes to exit before destroying.")
@pass_config_folder
def destroy_tunnel(config_folder_path: Path | None, name: str, wait: bool) -> None:
    config = ClientConfig.load(config_folder_path)

    async def _run() -> None:
        async with Client.connect(config) as client:
            await client.destroy_tunnel(name, wait=wait)

    asyncio.run(_run())
