from typing import Never

from radium226.vpn_passthrough.messages import ListRegions, RegionsListed, Country
from radium226.vpn_passthrough.ipc import Emit
from radium226.vpn_passthrough.pia import fetch_regions


async def handle(
    request: ListRegions,
    fds: list[int],
    emit: Emit[Never],
) -> tuple[RegionsListed, list[int]]:
    regions = await fetch_regions()
    countries = [
        Country(region_id=region.id, name=region.name, country=region.country)
        for region in regions
    ]
    return RegionsListed(request_id=request.id, countries=countries), []