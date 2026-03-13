import asyncio
import base64
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import httpx
from loguru import logger

from radium226.vpn_passthrough.vpn import Region, Session, EnterNamespace

from ._credentials import credentials_file
from ._models import Auth, ForwardedPort, Password, Payload, PayloadAndSignature, Signature, User
from ._run import run

__all__ = [
    "Auth",
    "ForwardedPort",
    "Password",
    "Payload",
    "PayloadAndSignature",
    "PIABackend",
    "PIASession",
    "Signature",
    "User",
    "connect",
    "fetch_regions",
    "Region",
]
from ._openvpn import OpenVPN

_DEFAULT_CA_CERT_PATH = Path(__file__).parent / "ca.rsa.4096.crt"
_SERVER_LIST_URL = "https://serverlist.piaservers.net/vpninfo/servers/v6"


def _auth_from_credentials(credentials: dict[str, str]) -> Auth:
    return Auth(user=User(credentials["username"]), password=Password(credentials["password"]))


class PIABackend:

    _REBIND_INTERVAL = 30.0

    @staticmethod
    async def _fetch_regions() -> list[Region]:
        async with httpx.AsyncClient() as http:
            response = await http.get(_SERVER_LIST_URL, timeout=10.0)
            response.raise_for_status()
        data = json.loads(response.text.split("\n", 1)[0])
        return [
            Region(
                id=region["id"],
                name=region["name"],
                country=region["country"],
                port_forward=region.get("port_forward", False),
            )
            for region in data.get("regions", [])
        ]

    @staticmethod
    async def _fetch_server(region_id: str) -> tuple[str, int]:
        async with httpx.AsyncClient() as http:
            response = await http.get(_SERVER_LIST_URL, timeout=10.0)
            response.raise_for_status()
        data = json.loads(response.text.split("\n", 1)[0])
        ports: list[int] = data.get("groups", {}).get("ovpnudp", [{}])[0].get("ports", [1198])
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

    async def _get_auth_token(self, auth: Auth) -> str:
        async with httpx.AsyncClient() as http:
            response = await http.post(
                "https://privateinternetaccess.com/api/client/v2/token",
                data={"username": auth.user, "password": auth.password},
                timeout=10.0,
            )
            response.raise_for_status()
        return response.json()["token"]

    async def _get_port_signature(
        self,
        gateway_ip: str, 
        token: 
        str, 
        enter_namespace: EnterNamespace,
    ) -> PayloadAndSignature:
        # The gateway is only reachable from inside the netns and uses a self-signed
        # certificate, so we reach it via curl run inside the namespace.
        _, stdout = await run(
            [
                "curl", "--silent", "--insecure", "-G",
                "--data-urlencode", f"token={token}",
                f"https://{gateway_ip}:19999/getSignature",
            ],
            check=True,
            preexec_fn=enter_namespace,
        )
        data = json.loads(stdout)
        return PayloadAndSignature(
            payload=Payload(data["payload"]),
            signature=Signature(data["signature"]),
        )

    def _decode_port(self, payload: Payload) -> int:
        return json.loads(base64.b64decode(payload))["port"]

    async def _bind_port(
        self,
        gateway_ip: str,
        pas: PayloadAndSignature,
        enter_namespace: EnterNamespace,
    ) -> None:
        _, stdout = await run(
            [
                "curl", "--silent", "--insecure", "-G",
                "--data-urlencode", f"payload={pas.payload}",
                "--data-urlencode", f"signature={pas.signature}",
                f"https://{gateway_ip}:19999/bindPort",
            ],
            check=True,
            preexec_fn=enter_namespace,
        )
        data = json.loads(stdout)
        if data.get("status") != "OK":
            logger.warning("Unexpected bindPort response: {}", data)

    async def _allocate_forwarded_port(
        self,
        gateway_ip: str, auth: Auth, enter_namespace: EnterNamespace
    ) -> ForwardedPort:
        token = await self._get_auth_token(auth)
        pas = await self._get_port_signature(gateway_ip, token, enter_namespace)
        port = self._decode_port(pas.payload)
        await self._bind_port(gateway_ip, pas, enter_namespace)
        logger.info("Forwarded port {} allocated", port)
        return ForwardedPort(number=port, payload_and_signature=pas)

    async def _rebind_loop(
        self,
        gateway_ip: str,
        forwarded_port: ForwardedPort,
        enter_namespace: EnterNamespace,
        interval: float = _REBIND_INTERVAL,
    ) -> None:
        while True:
            await asyncio.sleep(interval)
            try:
                await self._bind_port(gateway_ip, forwarded_port.payload_and_signature, enter_namespace)
                logger.debug("Port {} rebound", forwarded_port.number)
            except Exception:
                logger.warning(
                    "Failed to rebind port {}, will retry in {}s",
                    forwarded_port.number,
                    interval,
                )

    @asynccontextmanager
    async def connect(
        self,
        netns_name: str,
        *,
        enter_namespace: EnterNamespace,
        credentials: dict[str, str],
        region_id: str,
    ) -> AsyncIterator[Session]:
        auth = _auth_from_credentials(credentials)
        server_ip, server_port = await self._fetch_server(region_id)
        logger.info("Connecting to PIA region {} via {}:{}", region_id, server_ip, server_port)

        async with credentials_file(auth) as credentials_file_path:
            async with OpenVPN.connect(
                netns_name,
                server_ip,
                server_port,
                credentials_file_path,
                enter_namespace=enter_namespace,
                ca_cert_path=_DEFAULT_CA_CERT_PATH,
            ) as connection_info:
                @asynccontextmanager
                async def _forward_port() -> AsyncIterator[int]:
                    fp = await self._allocate_forwarded_port(connection_info.gateway_ip, auth, enter_namespace)
                    task = asyncio.create_task(self._rebind_loop(connection_info.gateway_ip, fp, enter_namespace))
                    try:
                        yield fp.number
                    finally:
                        task.cancel()
                        await asyncio.gather(task, return_exceptions=True)

                yield Session(
                    gateway_ip=connection_info.gateway_ip,
                    tun_ip=connection_info.tun_ip,
                    dns_servers=connection_info.dns_servers,
                    forward_port=_forward_port,
                )

    async def list_regions(self) -> list[Region]:
        return await self._fetch_regions()


async def fetch_regions() -> list[Region]:
    return await PIABackend._fetch_regions()
