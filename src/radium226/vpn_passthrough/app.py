from typing import Any
from click import (
    command, 
    group, 
    argument,
    option,
    UNPROCESSED,
    ParamType,
    Parameter, 
    Context,
)

from .vpn_passthrough import open_vpn_passthrough, VPNPassthrough
from .pia import list_servers 


@group()
def app() -> None:
    pass


@app.command()
@option("-n", "--name", "name", type=str, required=False)
@argument("command", nargs=-1, type=UNPROCESSED)
def exec(name: str | None, command: tuple[str, ...]) -> None:
    assert len(command) > 0, "Command must not be empty"

    name = name or command[0]
    with open_vpn_passthrough(name) as vpn_passthrough:
        vpn_passthrough.exec(list(command))


@app.group()
def pia() -> None:
    """Commands for managing PIA VPN passthrough."""


@pia.command("list-servers")
def _list_servers() -> None:
    list_servers()