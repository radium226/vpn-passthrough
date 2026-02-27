import asyncio
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator

from loguru import logger

from ._credentials import credentials_file
from ._gateway import allocate_forwarded_port, rebind_loop
from ._models import Auth, ForwardedPort, Password, Payload, PayloadAndSignature, RegionID, Signature, User

__all__ = [
    "allocate_forwarded_port",
    "Auth",
    "ForwardedPort",
    "Password",
    "Payload",
    "PayloadAndSignature",
    "PIA",
    "PIASession",
    "rebind_loop",
    "RegionID",
    "Signature",
    "User",
    "connect",
    "fetch_regions",
    "Region",
]
from ._openvpn import openvpn_connected
from ._models import Region
from ._server_list import fetch_regions, fetch_server

_DEFAULT_CA_CERT_PATH = Path(__file__).parent / "ca.rsa.4096.crt"


@dataclass(frozen=True)
class PIASession:
    gateway_ip: str
    tun_ip: str
    dns_servers: tuple[str, ...]
    forwarded_ports: tuple[ForwardedPort, ...]


@asynccontextmanager
async def connect(
    netns_name: str,
    auth: Auth,
    region_id: RegionID,
    *,
    enter_netns: Callable[[], None],
    ca_cert_path: Path = _DEFAULT_CA_CERT_PATH,
    forwarded_port_count: int = 0,
    rebind_interval: float = 30.0,
) -> AsyncIterator[PIASession]:
    """Connect the namespace to PIA VPN and yield a :class:`PIASession`.

    Steps:
    1. Fetch the PIA server list and pick a server for *region_id*.
    2. Write a temporary credentials file.
    3. Start OpenVPN inside the namespace and wait for it to connect.
    4. Allocate *forwarded_port_count* ports and start background rebind tasks.
    5. Yield the session; tear everything down on exit.
    """
    server_ip, server_port = await fetch_server(region_id)
    logger.info("Connecting to PIA region {} via {}:{}", region_id, server_ip, server_port)

    async with credentials_file(auth) as creds_path:
        async with openvpn_connected(
            netns_name,
            server_ip,
            server_port,
            creds_path,
            enter_netns=enter_netns,
            ca_cert_path=ca_cert_path,
        ) as (gateway_ip, tun_ip, dns_servers):
            forwarded_ports: list[ForwardedPort] = []
            for _ in range(forwarded_port_count):
                port = await allocate_forwarded_port(gateway_ip, auth, enter_netns)
                forwarded_ports.append(port)

            rebind_tasks = [
                asyncio.create_task(
                    rebind_loop(gateway_ip, port, enter_netns, rebind_interval)
                )
                for port in forwarded_ports
            ]

            try:
                yield PIASession(
                    gateway_ip=gateway_ip,
                    tun_ip=tun_ip,
                    dns_servers=tuple(dns_servers),
                    forwarded_ports=tuple(forwarded_ports),
                )
            finally:
                for task in rebind_tasks:
                    task.cancel()
                await asyncio.gather(*rebind_tasks, return_exceptions=True)


@dataclass(frozen=True)
class PIA:
    netns_name: str
    auth: Auth
    region_id: RegionID
    enter_netns: Callable[[], None]
    ca_cert_path: Path = _DEFAULT_CA_CERT_PATH
    forwarded_port_count: int = 0
    rebind_interval: float = 30.0

    def connect(self) -> AbstractAsyncContextManager[PIASession]:
        return connect(
            self.netns_name,
            self.auth,
            self.region_id,
            enter_netns=self.enter_netns,
            ca_cert_path=self.ca_cert_path,
            forwarded_port_count=self.forwarded_port_count,
            rebind_interval=self.rebind_interval,
        )


