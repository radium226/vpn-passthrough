import pytest
import os

from radium226.vpn_passthrough.shared.pia import PIA, Credentials


@pytest.fixture
async def pia():
    async with PIA.create(
        Credentials(
            user=os.environ["PIA_USER"],
            password=os.environ["PIA_PASS"],
        )
    ) as pia:
        yield pia


async def test_list_regions(pia: PIA):
    regions = await pia.list_regions()
    assert len(regions) > 0