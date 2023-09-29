from click import command, option, argument, group
from click_default_group import DefaultGroup
from random import choice

from ..commons import Credentials, User, Password, RegionName
from ..pia import PIA, ServerType
from ..network_namespace import NetworkNamespace, NetworkNamespaceName, executable


@group(cls=DefaultGroup, default='pass-through', default_if_no_args=True)
def app():
    pass


@executable(capture_output=False)
def run(command: list[str]) -> None:
    from subprocess import run
    run(command)


@app.command()
@option("--user", "-u", envvar="USER", type=User, required=True)
@option("--password", "-p", envvar="PASSWORD", type=Password, required=True)
@option("--region", "-r", "region_name", envvar="REGION", type=RegionName, required=False, default=None)
@option("--forward-port/--no-forward-port", default=True)
@option("--network-namespace", "-n", "network_namespace_name", type=NetworkNamespaceName, required=False, default="vpn-passthrough")
@argument("command", nargs=-1, type=str)
def pass_through(
    user: User, 
    password: Password,
    region_name: RegionName | None,
    forward_port: bool,
    network_namespace_name: NetworkNamespaceName,
    command: list[str],
):
    with NetworkNamespace(name=network_namespace_name) as network_namespace:
        pia = PIA(
            credentials=Credentials(
                user=user,
                password=password,
            ), 
            network_namespace=network_namespace,
        )
        with pia.through_tunnel(forward_port=forward_port) as tunnel:
           run(command, network_namespace=network_namespace)
            
                