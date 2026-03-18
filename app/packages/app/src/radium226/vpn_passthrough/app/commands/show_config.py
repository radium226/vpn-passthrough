from pathlib import Path

import click
import yaml

from radium226.vpn_passthrough.client import ClientConfig
from radium226.vpn_passthrough.server import ServerConfig
from radium226.vpn_passthrough.app.commands._helpers import pass_config_folder


@click.command("show-config")
@click.option("--empty", "empty", is_flag=True, default=False, help="Show default config values instead of the loaded config.")
@click.option("--server-only", "server_only", is_flag=True, default=False, help="Show only the server config section.")
@click.option("--client-only", "client_only", is_flag=True, default=False, help="Show only the client config section.")
@pass_config_folder
def show_config(config_folder_path: Path | None, empty: bool, server_only: bool, client_only: bool) -> None:
    if server_only:
        server_config = ServerConfig() if empty else ServerConfig.load(config_folder_path)
        data = {f.name: getattr(server_config, f.name) for f in server_config.__dataclass_fields__.values()}
        data = {k: str(v) if isinstance(v, Path) else v for k, v in data.items()}
    elif client_only:
        client_config = ClientConfig() if empty else ClientConfig.load(config_folder_path)
        data = client_config.model_dump(mode="json")
    else:
        server_config = ServerConfig() if empty else ServerConfig.load(config_folder_path)
        client_config = ClientConfig() if empty else ClientConfig.load(config_folder_path)
        server_data = {f.name: getattr(server_config, f.name) for f in server_config.__dataclass_fields__.values()}
        server_data = {k: str(v) if isinstance(v, Path) else v for k, v in server_data.items()}
        data = {
            "server": server_data,
            "client": client_config.model_dump(mode="json"),
        }
    click.echo(yaml.dump(data, default_flow_style=False), nl=False)
