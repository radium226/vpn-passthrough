import asyncio
import json
from pathlib import Path

import click
from prettytable import PrettyTable

from radium226.vpn_passthrough.client import Client, ClientConfig
from radium226.vpn_passthrough.app.commands._helpers import pass_config_folder


@click.command("list-regions")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["table", "json"]),
    default="table",
    help="Output format.",
)
@click.option("--backend-name", "backend_name", default=None, envvar="VPN_PASSTHROUGH_BACKEND", help="Backend name as configured in config file.")
@pass_config_folder
def list_regions(config_folder_path: Path | None, output_format: str, backend_name: str | None) -> None:
    config = ClientConfig.load(config_folder_path)

    async def _run() -> None:
        async with Client.connect(config) as client:
            countries = await client.list_regions(backend_name=backend_name)

            if output_format == "json":
                click.echo(json.dumps(
                    [{"region_id": country.region_id, "name": country.name, "country": country.country} for country in countries],
                    indent=2,
                ))
            else:
                table = PrettyTable()
                table.field_names = ["Region ID", "Name", "Country"]
                table.align = "l"
                for country in countries:
                    table.add_row([country.region_id, country.name, country.country])
                click.echo(table)

    asyncio.run(_run())
