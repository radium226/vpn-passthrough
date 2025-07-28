import asyncio
from typing import cast
from types import SimpleNamespace
from click import (
    group,
    option,
    argument,
    UNPROCESSED,
    pass_context, 
    Context
)
from loguru import logger
import sys


from ..shared.dbus import open_bus, BusScope
from ..server.dbus import TunnelManagerInterface

from .tunnel_manager import TunnelManager


@group() # cls=DefaultGroup, default="execute", default_if_no_args=True)
@option("--bus-scope", "bus_scope", type=BusScope, required=False)
@pass_context
def app(context: Context, bus_scope: BusScope | None) -> None:
    context.obj = SimpleNamespace()
    context.obj.bus_scope = bus_scope or BusScope.SYSTEM


@app.command()
@pass_context
def list_regions(context: Context) -> None:
    bus_scope = cast(BusScope, context.obj.bus_scope)

    async def coro() -> None:
        async with open_bus(bus_scope):
            tunnel_manager_interface = TunnelManagerInterface.new_proxy(
                "radium226.vpn_passthrough",
                "/radium226/vpn_passthrough/TunnelManager"
            )
            regions = await tunnel_manager_interface.region_ids.get_async()
            for region in regions:
                print(region)
    asyncio.run(coro())
            



@app.command()
@option("--region", "region_id", type=str, required=False)
@option("--name", "name", type=str, required=False)
@argument("command", nargs=-1, type=UNPROCESSED)
@pass_context
def execute(context: Context, command: tuple[str], region_id: str | None, name: str | None) -> None:
    bus_scope = cast(BusScope, context.obj.bus_scope)

    region_id = region_id or "france"
    name = name or "default"

    logger.debug(f"Executing command: {command} in region: {region_id} with name: {name} and bus scope: {bus_scope}")
    
    async def coro() -> int:
        async with open_bus(bus_scope):
            tunnel_manager = await TunnelManager.create()
            async with tunnel_manager.open_tunnel(name, region_id) as tunnel:
                logger.debug(f"Tunnel opened: {tunnel} in region {region_id}")
                execution = await tunnel.execute(command)
                logger.debug(f"Execution started: {execution}")
                exit_code = await execution.wait_for()
                logger.debug(f"Command executed with exit code: {exit_code}")
                return exit_code

    exit_code = asyncio.run(coro())
    sys.exit(exit_code if exit_code is not None else 0)