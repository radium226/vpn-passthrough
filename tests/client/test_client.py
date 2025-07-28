import pytest
from loguru import logger
import asyncio

from radium226.vpn_passthrough.client.tunnel_manager import TunnelManager

from .fixtures import *



@use_server
@pytest.mark.asyncio(loop_scope="session")
async def test_execute(tunnel_manager: TunnelManager):
    logger.debug(f"{tunnel_manager=}")
    assert tunnel_manager is not None
    
    async with tunnel_manager.open_tunnel("test", "france") as tunnel:
        logger.debug(f"{tunnel=}")
        assert tunnel is not None
        try:
            execution = await tunnel.execute(["echo", "Hello, World!"])
            logger.debug(f"{execution=}")
            assert execution is not None

            exit_code = await execution.wait_for()
            logger.debug(f"{exit_code=}")
            assert exit_code == 0
        except Exception as e:
            logger.error(f"Error during tunnel execution: {e}")
            pytest.fail(f"Tunnel execution failed: {e}")