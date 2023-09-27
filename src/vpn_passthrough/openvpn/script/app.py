from enum import StrEnum, auto
from ipaddress import IPv4Address
from pathlib import Path

from .bind_args_from_env import bind_args_from_env
from .script import ScriptClient


class ScriptType(StrEnum):

    UP = auto()

    DEBUG = auto()

    DOWN = auto()


@bind_args_from_env()
def app(
    script_type: ScriptType,
    route_vpn_gateway: str,
    NEW_NAMESERVER: str,
    OLD_NAMESERVER: str,
):
    client = ScriptClient()

    print(f"NEW_NAMESERVER={NEW_NAMESERVER}")

    match script_type:
        case ScriptType.DEBUG:
            client.debug()
    
        case ScriptType.UP:
            with Path("/etc/resolv.conf").open("w") as stream:
                stream.write(f"nameserver {NEW_NAMESERVER}")
            client.up(info={
                "route_vpn_gateway": route_vpn_gateway,
            })

        case ScriptType.DOWN:
            with Path("/etc/resolv.conf").open("w") as stream:
                stream.write(f"nameserver {OLD_NAMESERVER}")
            # client.down()