import pytest

from loguru import logger

from typing import AsyncGenerator
from contextlib import AsyncExitStack

from radium226.vpn_passthrough.shared.dbus import open_bus, BusScope
from radium226.vpn_passthrough.client.tunnel_manager import TunnelManager

from .server import server

@pytest.fixture(scope="session")
async def tunnel_manager(server) -> AsyncGenerator[TunnelManager, None]:
    logger.info("Creating TunnelManager fixture...")
    exit_stack = AsyncExitStack()
    try:
        tunnel_manager = await TunnelManager.create()
        yield tunnel_manager
    finally:
        await exit_stack.aclose()