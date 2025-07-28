from contextlib import asynccontextmanager
from loguru import logger
import asyncio
from typing import AsyncGenerator, Self


from ..shared.dbus import wait_for_property, to_be

from ..server.dbus import TunnelManagerInterface, TunnelInterface

from .tunnel import Tunnel


class TunnelManager():

    _interface: TunnelManagerInterface


    def __init__(self, interface: TunnelManagerInterface):
        self._interface = interface

    @classmethod
    async def create(cls) -> Self:
        path = "/radium226/vpn_passthrough/TunnelManager"
        interface = TunnelManagerInterface.new_proxy(
            "radium226.vpn_passthrough",
            path,
        )
        logger.debug("Creating TunnelManagerInterface proxy at path: {}", path)
        return cls(interface)


    @asynccontextmanager
    async def open_tunnel(self, tunnel_name: str, region_id: str) -> AsyncGenerator[Tunnel, None]:
        logger.debug(f"Opening tunnel '{tunnel_name}' with region '{region_id}'...")
        tunnel_path = await self._interface.open_tunnel(tunnel_name, region_id)
        logger.debug(f"Tunnel opened at path: {tunnel_path}")
        tunnel_interface = TunnelInterface.new_proxy(
            "radium226.vpn_passthrough",
            tunnel_path,
        )
        await wait_for_property(tunnel_interface.status, to_be("opened"))
        try:
            yield Tunnel(
                tunnel_name,    
                tunnel_interface,
            )
        except Exception as e:
            logger.error(f"Error while using tunnel '{tunnel_name}': {e}")
            raise
        finally:
            async def wait_for_tunnel_to_be_closed() -> None:
                logger.debug(f"Waiting for tunnel '{tunnel_name}' to be closed...")
                while True: 
                    if tunnel_path not in list((await self._interface.get_managed_objects()).keys()):
                        break
                    await asyncio.sleep(0.5)
                    
            wait_for_tunnel_closed_task = asyncio.create_task(wait_for_tunnel_to_be_closed())
            await self._interface.close_tunnel(tunnel_name)
            await wait_for_tunnel_closed_task

            # await wait_for_property(tunnel_interface.status, to_be("closed"))
            logger.debug(f"Tunnel {tunnel_name} closed.")