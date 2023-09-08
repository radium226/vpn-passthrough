from click import command, option, argument, group
from click_default_group import DefaultGroup
from random import choice

from ..commons import Credentials, User, Password, RegionName
from ..pia import PIA, ServerType
from ..network_namespace import NetworkNamespace, NetworkNamespaceName


@group(cls=DefaultGroup, default='pass-through', default_if_no_args=True)
def app():
    pass


@app.command()
@option("--user", "-u", envvar="USER", type=User, required=True)
@option("--password", "-p", envvar="PASSWORD", type=Password, required=True)
@option("--region", "-r", "region_name", envvar="REGION", type=RegionName, required=False, default=None)
@option("--port-forwarding/--no-port-forwarding", default=True)
@option("--network-namespace", "-n", "network_namespace_name", type=NetworkNamespaceName, required=False, default="vpn-passthrough")
@argument("command", nargs=-1, type=str)
def pass_through(
    user: User, 
    password: Password,
    region_name: RegionName | None,
    port_forwarding: bool,
    network_namespace_name: NetworkNamespaceName,
    command: list[str],
):
    pass
    # with NetworkNamespace(name=network_namespace_name) as network_namespace:
    #     credentials = Credentials(user, password)
    #     with PIA(credentials=credentials) as pia:
    #         if region_name:
    #             region = pia.regions_by_name.get(region_name, None)
    #         else:
    #             regions = pia.regions_by_name.values()
    #             if port_forwarding:
    #                 regions = [region for region in regions if region.supports_port_forwarding]
    #             region = choice(regions)

    #         if not region:
    #             raise Exception("Unable to find region! ")

    #         with pia.openvpn(region=region, network_namespace=network_namespace) as openvpn:
    #             port = pia.bind_port_to_forward(region=region)

    
    