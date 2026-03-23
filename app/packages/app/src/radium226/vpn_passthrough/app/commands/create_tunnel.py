import asyncio
import signal
from pathlib import Path

import click

from radium226.vpn_passthrough.client import Client, ClientConfig, TunnelConfig
from radium226.vpn_passthrough.app.commands._helpers import pass_config_folder


@click.command("create-tunnel")
@click.option("--region-id", default=None, envvar="VPN_PASSTHROUGH_REGION_ID", help="VPN region ID. If omitted, falls back to config file, then a random region is chosen.")
@click.option("--backend-name", "backend_name", default=None, envvar="VPN_PASSTHROUGH_BACKEND", help="Backend name as configured in config file.")
@click.option("--forward-port-for", "names_of_ports_to_forward", multiple=True, help="Forward a port with the given name (repeatable, e.g. --forward-port-for transmission).")
@click.option("--veth-cidr", "veth_cidr", default=None, help="Fixed CIDR for the veth pair (e.g. 10.200.5.0/24). If omitted, an address is derived from the tunnel name.")
@click.option("--kill-switch", "kill_switch", type=click.Choice(["yes", "no"]), default=None, help="Block all traffic that bypasses the VPN tunnel (default: yes).")
@click.option("--forward-vpeer-port-to-loopback", "ports_to_forward_from_vpeer_to_loopback", multiple=True, type=int, help="DNAT this port on the vpeer to 127.0.0.1 inside the tunnel (repeatable).")
@click.argument("name")
@pass_config_folder
def create_tunnel(config_folder_path: Path | None, region_id: str | None, backend_name: str | None, names_of_ports_to_forward: tuple[str, ...], veth_cidr: str | None, kill_switch: str | None, ports_to_forward_from_vpeer_to_loopback: tuple[int, ...], name: str) -> None:
    client_config = ClientConfig.load(config_folder_path)
    tunnel_configs = TunnelConfig.load_all(config_folder_path)
    tunnel_config = tunnel_configs.get(name, TunnelConfig(name=name))
    region_id = region_id or tunnel_config.region_id
    resolved_names = list(names_of_ports_to_forward) if names_of_ports_to_forward else tunnel_config.names_of_ports_to_forward
    veth_cidr = veth_cidr or tunnel_config.veth_cidr
    resolved_kill_switch = (kill_switch == "yes") if kill_switch is not None else tunnel_config.kill_switch
    resolved_ports = list(ports_to_forward_from_vpeer_to_loopback) if ports_to_forward_from_vpeer_to_loopback else tunnel_config.ports_to_forward_from_vpeer_to_loopback

    async def _run() -> None:
        async with Client.connect(client_config) as client:
            loop = asyncio.get_running_loop()
            stop: asyncio.Future[None] = loop.create_future()

            def _stop() -> None:
                if not stop.done():
                    stop.set_result(None)

            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, _stop)

            created = False
            try:
                await client.create_tunnel(name, region_id=region_id, names_of_ports_to_forward=resolved_names, backend_name=backend_name, veth_cidr=veth_cidr, kill_switch=resolved_kill_switch, ports_to_forward_from_vpeer_to_loopback=resolved_ports)
                created = True
                await stop
            finally:
                for sig in (signal.SIGINT, signal.SIGTERM):
                    loop.remove_signal_handler(sig)
                if created:
                    await client.destroy_tunnel(name)

    asyncio.run(_run())
