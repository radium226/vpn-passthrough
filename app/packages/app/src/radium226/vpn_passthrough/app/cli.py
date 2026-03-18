from pathlib import Path
from types import SimpleNamespace

import click

from radium226.vpn_passthrough.app.commands.start_server import start_server
from radium226.vpn_passthrough.app.commands.run_process import run_process
from radium226.vpn_passthrough.app.commands.debug_tunnel import debug_tunnel
from radium226.vpn_passthrough.app.commands.create_tunnel import create_tunnel
from radium226.vpn_passthrough.app.commands.start_tunnel import start_tunnel
from radium226.vpn_passthrough.app.commands.list_regions import list_regions
from radium226.vpn_passthrough.app.commands.list_tunnels import list_tunnels
from radium226.vpn_passthrough.app.commands.list_backends import list_backends
from radium226.vpn_passthrough.app.commands.show_config import show_config
from radium226.vpn_passthrough.app.commands.destroy_tunnel import destroy_tunnel


@click.group()
@click.option(
    "--config",
    "config_folder_path",
    type=Path,
    default=None,
    envvar="VPN_PASSTHROUGH_CONFIG",
    help="Path to a config folder containing server.yaml, client.yaml, and tunnels/.",
)
@click.pass_context
def app(ctx: click.Context, config_folder_path: Path | None) -> None:
    ctx.ensure_object(SimpleNamespace)
    ctx.obj.config_folder_path = config_folder_path


app.add_command(start_server)
app.add_command(run_process)
app.add_command(debug_tunnel)
app.add_command(create_tunnel)
app.add_command(start_tunnel)
app.add_command(list_regions)
app.add_command(list_tunnels)
app.add_command(list_backends)
app.add_command(show_config)
app.add_command(destroy_tunnel)
