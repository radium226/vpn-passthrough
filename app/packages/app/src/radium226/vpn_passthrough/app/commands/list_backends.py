from pathlib import Path

import click

from radium226.vpn_passthrough.server import ServerConfig
from radium226.vpn_passthrough.app.commands._helpers import pass_config_folder


@click.command("list-backends")
@pass_config_folder
def list_backends(config_folder_path: Path | None) -> None:
    config = ServerConfig.load(config_folder_path)

    from radium226.vpn_passthrough.vpn import list_backends as list_backends_fn
    from radium226.vpn_passthrough.server import BackendConfig
    from radium226.vpn_passthrough.messages import BackendInfo
    backends = [BackendInfo(name=backend_config.name, type=backend_config.type, credentials=backend_config.credentials) for backend_config in BackendConfig.load_all(config.backends_folder_path)]
    available_types = list(list_backends_fn())
    click.echo("Configured backends:")
    if backends:
        for backend in backends:
            username = backend.credentials.get("username", "")
            password = backend.credentials.get("password", "")
            masked_password = "*" * len(password) if password else ""
            credentials_str = f", username: {username}, password: {masked_password}" if username or password else ""
            click.echo(f"  {backend.name} (type: {backend.type}{credentials_str})")
    else:
        click.echo("  (none)")
    click.echo("\nAvailable backend types:")
    for backend_type in available_types:
        click.echo(f"  {backend_type}")
