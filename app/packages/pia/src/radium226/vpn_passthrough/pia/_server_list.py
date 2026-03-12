import json

import httpx
from loguru import logger

from radium226.vpn_passthrough.vpn import Region

from ._models import RegionID

_SERVER_LIST_URL = "https://serverlist.piaservers.net/vpninfo/servers/v6"


async def fetch_regions() -> list[Region]:
    """Return all available PIA regions."""
    async with httpx.AsyncClient() as http:
        response = await http.get(_SERVER_LIST_URL, timeout=10.0)
        response.raise_for_status()

    data = json.loads(response.text.split("\n", 1)[0])

    return [
        Region(
            id=RegionID(region["id"]),
            name=region["name"],
            country=region["country"],
            port_forward=region.get("port_forward", False),
        )
        for region in data.get("regions", [])
    ]


async def fetch_server(region_id: RegionID) -> tuple[str, int]:
    """Return *(server_ip, port)* for *region_id* using the PIA server list."""
    async with httpx.AsyncClient() as http:
        response = await http.get(_SERVER_LIST_URL, timeout=10.0)
        response.raise_for_status()

    # The response body is: <json>\n<certificate>  — parse only the JSON part.
    data = json.loads(response.text.split("\n", 1)[0])

    ports: list[int] = (
        data.get("groups", {}).get("ovpnudp", [{}])[0].get("ports", [1198])
    )

    for region in data.get("regions", []):
        if region["id"] == region_id:
            servers = region["servers"].get("ovpnudp", [])
            if not servers:
                raise ValueError(f"No OpenVPN UDP servers for region {region_id!r}")
            ip: str = servers[0]["ip"]
            port: int = ports[0]
            logger.debug("PIA server for region {}: {}:{}", region_id, ip, port)
            return ip, port

    raise ValueError(f"Region {region_id!r} not found in PIA server list")
