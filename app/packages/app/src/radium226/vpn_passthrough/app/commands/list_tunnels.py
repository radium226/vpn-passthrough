import asyncio
import json
from pathlib import Path

import click
from prettytable import PrettyTable

from radium226.vpn_passthrough.client import Client, ClientConfig
from radium226.vpn_passthrough.app.commands._helpers import pass_config_folder


@click.command("list-tunnels")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["table", "json"]),
    default="table",
    help="Output format.",
)
@click.option("--with-processes", "with_processes", is_flag=True, default=False, help="Include running processes per tunnel.")
@pass_config_folder
def list_tunnels(config_folder_path: Path | None, output_format: str, with_processes: bool) -> None:
    config = ClientConfig.load(config_folder_path)

    async def _run() -> None:
        async with Client.connect(config) as client:
            tunnels = await client.list_tunnels()

            if output_format == "json":
                click.echo(json.dumps(
                    [
                        {
                            "name": tunnel.name,
                            "vpn_connected": tunnel.vpn_connected,
                            "region_id": tunnel.region_id,
                            "public_ip": tunnel.public_ip,
                            "gateway_ip": tunnel.gateway_ip,
                            "tun_ip": tunnel.tun_ip,
                            "veth_ip": tunnel.veth_ip,
                            "vpeer_ip": tunnel.vpeer_ip,
                            "forwarded_ports": tunnel.forwarded_ports,
                            **({"processes": [{"pid": process.pid, "command": process.command, "args": process.args} for process in tunnel.processes]} if with_processes else {}),
                        }
                        for tunnel in tunnels
                    ],
                    indent=2,
                ))
            else:
                fields = ["Name", "VPN", "Region", "Public IP", "Gateway IP", "Tun IP", "Veth IP", "Vpeer IP", "Forwarded Ports"]
                if with_processes:
                    fields.append("Processes")
                table = PrettyTable()
                table.field_names = fields
                table.align = "l"
                for tunnel in tunnels:
                    row = [
                        tunnel.name,
                        "yes" if tunnel.vpn_connected else "no",
                        tunnel.region_id or "",
                        tunnel.public_ip or "",
                        tunnel.gateway_ip or "",
                        tunnel.tun_ip or "",
                        tunnel.veth_ip or "",
                        tunnel.vpeer_ip or "",
                        ", ".join(f"{port_name}={port_number}" for port_name, port_number in tunnel.forwarded_ports.items()),
                    ]
                    if with_processes:
                        row.append("\n".join(f"{process.pid}: {process.command} {' '.join(process.args)}".strip() for process in tunnel.processes))
                    table.add_row(row)
                click.echo(table)

    asyncio.run(_run())
