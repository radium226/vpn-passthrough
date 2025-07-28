from typing import AsyncGenerator, Self, Callable, Coroutine
from contextlib import AsyncExitStack, asynccontextmanager
from loguru import logger
from sdbus import (
    dbus_property_async,
    dbus_method_async,
    DbusObjectManagerInterfaceAsync,
    DbusUnprivilegedFlag,
)
import asyncio
import traceback
from dataclasses import dataclass

from ..core import TunnelManager

from .tunnel_interface import TunnelInterface

from ...shared.pia import Region


@dataclass
class Context():

    tunnel_interface: TunnelInterface
    close_tunnel: Callable[[], Coroutine[None, None, None]]


class TunnelManagerInterface(
    DbusObjectManagerInterfaceAsync,
    interface_name="radium226.vpn_passthrough.TunnelManager",
):

    _region_ids: list[str]
    _tunnel_manager: TunnelManager
    _exit_stack: AsyncExitStack

    _contexts_by_name: dict[str, Context] = {}


    @classmethod
    @asynccontextmanager 
    async def start(cls, tunnel_manager: TunnelManager) -> AsyncGenerator[Self, None]:
        interface = cls(tunnel_manager)
        await interface._reload_regions()
        
        # Scheduling a periodic task to reload regions every 30 seconds
        async def _reload_regions_periodically(interval_in_seconds: int = 2 * 60 * 60) -> None: # 2 hours
            while True:
                try:
                    await asyncio.sleep(interval_in_seconds)
                    await interface._reload_regions()
                except asyncio.CancelledError:
                    logger.debug("Reload regions task cancelled.")
                    break

        reload_regions_tasks = asyncio.create_task(_reload_regions_periodically())
        
        logger.debug("Exporting TunnelManagerInterface to DBus...")
        export_handle = interface.export_to_dbus(
            "/radium226/vpn_passthrough/TunnelManager"
        )
        logger.debug("Exported! ")

        try:
            yield interface
        finally:
            export_handle.stop()
            reload_regions_tasks.cancel()
            await reload_regions_tasks
            await interface.stop()


    def __init__(self, tunnel_manager: TunnelManager):
        super().__init__()
        self._tunnel_manager = tunnel_manager
        self._exit_stack = AsyncExitStack()
        self._region_ids = []


    async def stop(self) -> None:
        logger.debug("Stopping TunnelManagerInterface...")
        await self._exit_stack.aclose()
        logger.debug("Stopped! ")


    async def _reload_regions(self) -> None:
        logger.debug("Reloading region ids...")
        regions = await self._tunnel_manager.list_regions()
        region_ids = [region.id for region in regions]
        await self.region_ids.set_async(region_ids)
        logger.debug("Reloaded! ")


    @dbus_property_async(
        property_name="Regions",
        property_signature="as",
    )
    def region_ids(self) -> list[str]:
        logger.debug("Getting region ids...")
        return self._region_ids
    

    @region_ids.setter_private
    def _set_region_ids(self, region_ids: list[str]) -> None:
        logger.trace("_set_region_ids({region_ids})", region_ids=region_ids)
        self._region_ids = region_ids
    

    async def _get_region_by_id(self, region_id: str) -> Region:
        region = next(filter(lambda r: r.id == region_id, await self._tunnel_manager.list_regions()), None)
        if region is None:
            raise ValueError(f"Region '{region_id}' not found.")
        return region


    @dbus_method_async(
        method_name="OpenTunnel",
        input_signature="ss",
        result_signature="o",
        input_args_names=["name", "region"],
        result_args_names=["tunnel_path"],
        flags=DbusUnprivilegedFlag,
    )
    async def open_tunnel(
        self,
        name: str,
        region_id: str,
    ) -> str:
        logger.debug("Opening tunnel with name: {name}, region_id: {region_id}", name=name, region_id=region_id)
        try:
            region = await self._get_region_by_id(region_id)
            tunnel_path = f"/radium226/vpn_passthrough/TunnelManager/Tunnel/{name}"
            tunnel_interface = TunnelInterface(
                initial_status="opening",
            )
            export_handle = self.export_with_manager(
                tunnel_path,
                tunnel_interface,
            )
            logger.debug("TunnelInterface exported at path: {tunnel_path}", tunnel_path=tunnel_path)

            context_manager = self._tunnel_manager.open_tunnel(name, region)

            async def _open_tunnel() -> None:
                logger.debug("Opening tunnel with context manager...")

                tunnel = await context_manager.__aenter__()
                logger.debug("Yieleded tunnel: {tunnel}", tunnel=tunnel)

                tunnel_interface.tunnel = tunnel
                logger.debug("Tunnel opened: {tunnel}", tunnel=tunnel)
                await tunnel_interface.status.set_async("opened")

                tunnel_info = await tunnel.lookup_info()
                await tunnel_interface.ip.set_async(tunnel_info.ip)

            asyncio.create_task(_open_tunnel())

            async def _close_tunnel() -> None:
                try:
                    logger.debug("Actually closing tunnel...")
                    await context_manager.__aexit__(None, None, None)
                    await tunnel_interface.status.set_async("closed")
                    # await asyncio.sleep(5)  # Give some time for the status to propagate
                    export_handle.stop()
                except Exception as e:
                    logger.error(f"Error while closing tunnel: {e}")
            
            self._contexts_by_name[name] = Context(
                tunnel_interface=tunnel_interface,
                close_tunnel=_close_tunnel,
            )
            return tunnel_path
        except Exception as e:
            logger.error(f"Failed to create tunnel: {e}")
            traceback.print_exc()
            raise e


    @dbus_method_async(
        method_name="CloseTunnel",
        input_signature="s",
        result_signature="",
        input_args_names=["tunnel"],
        flags=DbusUnprivilegedFlag,
    )
    async def close_tunnel(self, tunnel_name: str) -> None:
        logger.debug("Closing tunnel with name: {tunnel_name}", tunnel_name=tunnel_name)
        if tunnel_name not in self._contexts_by_name:
            logger.warning(f"Tunnel '{tunnel_name}' not found.")
            return
        
        context = self._contexts_by_name[tunnel_name]
        await context.tunnel_interface.status.set_async("closing")
        asyncio.create_task(context.close_tunnel())