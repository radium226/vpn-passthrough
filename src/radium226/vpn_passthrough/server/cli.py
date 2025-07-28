from click import command, option
import asyncio
from contextlib import AsyncExitStack
from loguru import logger

from ..shared.dbus import open_bus, BusScope
from ..shared.pia import PIA, Credentials

from .core import TunnelManager

from .dbus import (
    TunnelManagerInterface
)


@command()
@option(
    "-u", 
    "--pia-user", 
    "pia_user", 
    type=str, 
    required=True,
    envvar="PIA_USER",
)
@option(
    "-p", 
    "--pia-password",
    "pia_password",
    type=str,
    required=True,
    envvar="PIA_PASS",
)
@option(
    "-b",
    "--bus-scope", "bus_scope", 
    type=BusScope, 
    required=False,
)
def app(bus_scope: BusScope | None, pia_user: str, pia_password: str) -> None:
    bus_scope = bus_scope or BusScope.auto()
    pia_credentials = Credentials(
        user=pia_user,
        password=pia_password,
    )

    logger.debug(f"Starting VPN Passthrough Client with bus scope: {bus_scope}")
    async def coro() -> None:
        exit_stack = AsyncExitStack()
        try:
            logger.debug("Creating TunnelManager... ")
            pia = await exit_stack.enter_async_context(PIA.create(pia_credentials))
            tunnel_manager = await exit_stack.enter_async_context(
                TunnelManager.create(pia)
            )
            logger.debug("Created! ")

            logger.debug("Opening DBus session... ")
            bus = await exit_stack.enter_async_context(
                open_bus(bus_scope)
            )
            await bus.request_name_async("radium226.vpn_passthrough", 0)
            await exit_stack.enter_async_context(
                TunnelManagerInterface.start(tunnel_manager)
            )
            logger.debug("Opened! ")

            await asyncio.Event().wait()
        finally:
            await exit_stack.aclose()

    asyncio.run(coro())