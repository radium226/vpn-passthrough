from dataclasses import dataclass, field
from typing import Generator, Optional
import requests
import json
from pathlib import Path
from tempfile import NamedTemporaryFile

from contextlib import contextmanager


SERVERS_URL = "https://serverlist.piaservers.net/vpninfo/servers/v6"

OPENVPN_PORT = 1198  # Default OpenVPN port, can be overridden by the server list

NAMESERVER_IP_ADDR = "10.0.0.242"


@dataclass
class Credentials():
    user: str
    password: str

    @contextmanager
    def to_file(self) -> Generator[Path, None, None]:
        with NamedTemporaryFile(delete=False, mode='w') as stream:
            stream.write(f"{self.user}\n{self.password}")
            stream.flush()
            yield Path(stream.name)


@dataclass
class Server:
    ip: str
    cn: str
    van: Optional[bool] = None  # van is optional, only present in ovpntcp and ovpnudp


@dataclass
class Servers:
    ikev2: list[Server]
    meta: list[Server]
    ovpntcp: list[Server]
    ovpnudp: list[Server]
    wg: list[Server]

@dataclass
class Region:
    id: str
    name: str
    country: str
    auto_region: bool
    dns: str
    port_forward: bool
    geo: bool
    offline: bool
    servers: Servers


def list_regions() -> list[Region]:
    response = requests.get(SERVERS_URL, headers={"Accept": "application/json"})
    response.raise_for_status()
    [text, *_] = response.text.splitlines()
    data = json.loads(text)

    def iter_regions() -> Generator[Region, None, None]:
        for region_obj in data["regions"]:
            # Parse each server type list
            servers_obj = region_obj["servers"]
            ikev2_servers = [Server(**server_obj) for server_obj in servers_obj.get('ikev2', [])]
            meta_servers = [Server(**server_obj) for server_obj in servers_obj.get('meta', [])]
            ovpntcp_servers = [Server(**server_obj) for server_obj in servers_obj.get('ovpntcp', [])]
            ovpnudp_servers = [Server(**server_obj) for server_obj in servers_obj.get('ovpnudp', [])]
            wg_servers = [Server(**server_obj) for server_obj in servers_obj.get('wg', [])]

            servers = Servers(
                ikev2=ikev2_servers,
                meta=meta_servers,
                ovpntcp=ovpntcp_servers,
                ovpnudp=ovpnudp_servers,
                wg=wg_servers
            )

            yield Region(
                id=region_obj['id'],
                name=region_obj['name'],
                country=region_obj['country'],
                auto_region=region_obj['auto_region'],
                dns=region_obj['dns'],
                port_forward=region_obj['port_forward'],
                geo=region_obj['geo'],
                offline=region_obj['offline'],
                servers=servers
            )

    return list(iter_regions())