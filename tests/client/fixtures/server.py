import pytest

import os
from loguru import logger
from typing import AsyncGenerator
from contextlib import AsyncExitStack
from asyncio import sleep

from radium226.vpn_passthrough.server.core import TunnelManager, TestMode
from radium226.vpn_passthrough.shared.pia import PIA, Credentials
from radium226.vpn_passthrough.shared.dbus import open_bus, BusScope
from radium226.vpn_passthrough.server.dbus import TunnelManagerInterface



@pytest.fixture(scope="session")
async def server() -> AsyncGenerator[None, None]:
    logger.info("Starting server... ")
    exit_stack = AsyncExitStack()
    try:
        pia = await exit_stack.enter_async_context(PIA.create(
            Credentials(
                user=os.environ["PIA_USER"],
                password=os.environ["PIA_PASS"],
            )
        ))
        tunnel_manager = await exit_stack.enter_async_context(TunnelManager.create(pia, test_mode=TestMode.UNIT))
        bus = await exit_stack.enter_async_context(open_bus(BusScope.SESSION))
        await bus.request_name_async("radium226.vpn_passthrough", 0)
        await exit_stack.enter_async_context(TunnelManagerInterface.start(tunnel_manager))
        # FIXME: Replace the sleep by a real check by doing a call to DBus
        await sleep(1)
        yield None
    finally:
        logger.info("Stopping server... ")
        await exit_stack.aclose()



use_server = pytest.mark.usefixtures("server")