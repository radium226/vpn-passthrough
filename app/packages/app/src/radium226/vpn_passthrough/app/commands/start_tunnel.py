import asyncio
import signal
from pathlib import Path

import click
from loguru import logger

from radium226.vpn_passthrough.client import Client, ClientConfig, TunnelConfig
from radium226.vpn_passthrough.messages import ConfigUsed, PortsRebound, TunnelInfo
from radium226.vpn_passthrough.app.systemd import sd_notify
from radium226.vpn_passthrough.app.commands._helpers import pass_config_folder


@click.command("start-tunnel")
@click.option("--region-id", default=None, envvar="VPN_PASSTHROUGH_REGION_ID", help="VPN region ID. If omitted, falls back to config, then a random region is chosen.")
@click.option("--backend-name", "backend_name", default=None, envvar="VPN_PASSTHROUGH_BACKEND", help="Backend name as configured in config file.")
@click.option("--forward-port-for", "names_of_ports_to_forward", multiple=True, help="Forward a port with the given name (repeatable, e.g. --forward-port-for transmission).")
@click.option("--rebind-ports-every", "rebind_ports_every", type=float, default=None, help="Reallocate forwarded ports every N seconds (default: from config).")
@click.option("--veth-cidr", "veth_cidr", default=None, help="Fixed CIDR for the veth pair (e.g. 10.200.5.0/24). If omitted, an address is derived from the tunnel name.")
@click.option("--kill-switch", "kill_switch", type=click.Choice(["yes", "no"]), default=None, help="Block all traffic that bypasses the VPN tunnel (default: yes).")
@click.option("--forward-vpeer-port-to-loopback", "ports_to_forward_from_vpeer_to_loopback", multiple=True, type=int, help="DNAT this port on the vpeer to 127.0.0.1 inside the tunnel (repeatable).")
@click.argument("name")
@pass_config_folder
def start_tunnel(config_folder_path: Path | None, region_id: str | None, backend_name: str | None, names_of_ports_to_forward: tuple[str, ...], rebind_ports_every: float | None, veth_cidr: str | None, kill_switch: str | None, ports_to_forward_from_vpeer_to_loopback: tuple[int, ...], name: str) -> None:
    client_config = ClientConfig.load(config_folder_path)
    tunnel_configs = TunnelConfig.load_all(config_folder_path)
    tunnel_config = tunnel_configs.get(name, TunnelConfig(name=name))
    region_id = region_id or tunnel_config.region_id
    resolved_names = list(names_of_ports_to_forward) if names_of_ports_to_forward else tunnel_config.names_of_ports_to_forward
    rebind_ports_every = rebind_ports_every if rebind_ports_every is not None else tunnel_config.rebind_ports_every
    veth_cidr = veth_cidr or tunnel_config.veth_cidr
    resolved_kill_switch = (kill_switch == "yes") if kill_switch is not None else tunnel_config.kill_switch
    resolved_ports = list(ports_to_forward_from_vpeer_to_loopback) if ports_to_forward_from_vpeer_to_loopback else tunnel_config.ports_to_forward_from_vpeer_to_loopback

    async def _run() -> None:
        async with Client.connect(client_config) as client:
            loop = asyncio.get_running_loop()
            stopping = False

            def on_ready() -> None:
                sd_notify("READY=1")

            def on_config_used(config_used: ConfigUsed) -> None:
                lines = [
                    f"  backend_name:             {config_used.backend_name or '(none)'}",
                    f"  region_id:                {config_used.region_id or '(none)'}",
                    f"  names_of_ports_to_forward:  {config_used.names_of_ports_to_forward}",
                ]
                click.echo("Config used:\n" + "\n".join(lines))

            def on_tunnel_status_updated(info: TunnelInfo) -> None:
                process_count = len(info.processes)
                word = "process" if process_count == 1 else "processes"
                sd_notify(f"STATUS={process_count} {word} running")

            def on_ports_rebound(event: PortsRebound) -> None:
                parts = ", ".join(f"{port_name}={port_number}" for port_name, port_number in event.forwarded_ports.items())
                click.echo(f"Ports rebound: {parts}")

            def _stop(sig: signal.Signals) -> None:
                nonlocal stopping
                if stopping:
                    return
                stopping = True
                logger.warning("Received {}, stopping tunnel {}", sig.name, name)
                asyncio.create_task(client.destroy_tunnel(name))

            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, _stop, sig)
            try:
                await client.start_tunnel(
                    name,
                    region_id=region_id,
                    names_of_ports_to_forward=resolved_names,
                    backend_name=backend_name,
                    rebind_ports_every=rebind_ports_every,
                    veth_cidr=veth_cidr,
                    kill_switch=resolved_kill_switch,
                    ports_to_forward_from_vpeer_to_loopback=resolved_ports,
                    on_ready=on_ready,
                    on_config_used=on_config_used,
                    on_tunnel_status_updated=on_tunnel_status_updated,
                    on_ports_rebound=on_ports_rebound,
                )
            finally:
                for sig in (signal.SIGINT, signal.SIGTERM):
                    loop.remove_signal_handler(sig)

    asyncio.run(_run())
