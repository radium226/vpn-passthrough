import pytest
import os
from loguru import logger

from radium226.vpn_passthrough.shared.pia import PIA, Credentials
from radium226.vpn_passthrough.server.core import TunnelManager, Tunnel

sudo = pytest.mark.sudo


@pytest.fixture
async def uk_tunnel():
    pia_credentials = Credentials(
        user=os.environ["PIA_USER"],
        password=os.environ["PIA_PASS"],
    )

    async with PIA.create(pia_credentials) as pia:
        regions = await pia.list_regions()
        assert len(regions) > 0
        
        region = next((region for region in regions if region.id == "uk"), None)
        assert region is not None

        async with TunnelManager.create(pia) as tunnel_manager:
            async with tunnel_manager.open_tunnel("uk-tunnel", region) as tunnel:
                yield tunnel


@sudo
@pytest.mark.skip
@pytest.mark.parametrize(
    "region_id, expected_region", 
    [
        ("uk", "England"), 
        ("france", "Île-de-France"),
    ]
)
async def test_tunnel(region_id: str, expected_region: str):
    pia_credentials = Credentials(
        user=os.environ["PIA_USER"],
        password=os.environ["PIA_PASS"],
    )

    async with PIA.create(pia_credentials) as pia:
        regions = await pia.list_regions()
        assert len(regions) > 0
        
        region = next((region for region in regions if region.id == region_id), None)
        assert region is not None

        async with TunnelManager.create(pia) as tunnel_manager:
            async with tunnel_manager.open_tunnel("tunnel", region) as tunnel:
                info = await tunnel.lookup_info()
                assert info.ip is not None
                assert info.city is not None
                assert info.region == expected_region



@sudo
async def test_forward_port(uk_tunnel: Tunnel):
    logger.info("Here we go! ")
    port = await uk_tunnel.forward_port()