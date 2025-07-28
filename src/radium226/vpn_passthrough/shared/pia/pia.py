from typing import (
    Generator, 
    Self,
    AsyncGenerator,
)
from loguru import logger
from httpx import AsyncClient
import json
from contextlib import asynccontextmanager
from asyncio.subprocess import create_subprocess_exec, PIPE

from .types import (
    Region, 
    Server,
    Servers,
    Credentials, 
    PayloadAndSignature,
)
from .constants import SERVERS_URL
from base64 import b64decode



class PIA:

    AUTH_TOKEN_URL = "https://www.privateinternetaccess.com/api/client/v2/token"
    DIP_URL = "https://www.privateinternetaccess.com/api/client/v2/dedicated_ip"
    SERVERS_URL = "https://serverlist.piaservers.net/vpninfo/servers/v6"

    _client: AsyncClient
    _credentials: Credentials

    def __init__(self, client: AsyncClient, credentials: Credentials):
        self._client = client
        self._credentials = credentials


    @property
    def credentials(self) -> Credentials:
        return self._credentials


    @classmethod
    @asynccontextmanager
    async def create(cls, credentials: Credentials) -> AsyncGenerator[Self, None]:
        async_client = AsyncClient()
        try:
            instance = cls(async_client, credentials)
            yield instance
        finally:
            await instance.destroy()

    async def destroy(self) -> None:
        logger.debug("Destroying PIA...")
        await self._client.aclose()
        logger.debug("Destroyed! ")


    async def list_regions(self) -> list[Region]:
        response = await self._client.get(SERVERS_URL, headers={"Accept": "application/json"})
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
    

    async def generate_auth_token(self) -> str:
        data = {
            "username": self._credentials.user,
            "password": self._credentials.password,
        }
        async with AsyncClient() as http_client:
            response = await http_client.post(
                self.AUTH_TOKEN_URL,
                data=data,
                follow_redirects=True,
            )
        response.raise_for_status()
        obj = response.json()
        auth_token = obj["token"]
        assert isinstance(auth_token, str), "Auth token must be a string"
        return auth_token
    

    async def lookup_gateway(self) -> str:
        process = await create_subprocess_exec(
            "ip", "route", "show", "0.0.0.0/1",
            stdout=PIPE,
        )
        stdout, _ = await process.communicate()
        gateway = stdout.decode("utf-8").split(" ")[2]
        return gateway


    async def generate_payload_and_signature(self) -> PayloadAndSignature:
        gateway = await self.lookup_gateway()
        auth_token = await self.generate_auth_token()
        logger.debug(f"gateway={gateway}, auth_token={auth_token}")

        async with AsyncClient(verify=False) as http_client:
            response = await http_client.get(
                f"https://{gateway}:19999/getSignature",
                params={"token": auth_token},
            )
        response.raise_for_status()
        obj = response.json()
        payload = obj["payload"]
        signature = obj["signature"]
        payload_and_signature = PayloadAndSignature(
            payload=payload,
            signature=signature,
        )
        return payload_and_signature

    
    async def request_port(self) -> tuple[int, PayloadAndSignature]:
        payload_and_signature = await self.generate_payload_and_signature()
        payload = payload_and_signature.payload
        obj = json.loads(b64decode(payload).decode("utf-8"))
        port = int(obj["port"])
        return port, payload_and_signature
    

    async def bind_port(self, payload_and_signature: PayloadAndSignature) -> None:
        payload = payload_and_signature.payload
        signature = payload_and_signature.signature
        gateway = await self.lookup_gateway()
    
        async with AsyncClient(verify=False) as http_client:
            response = await http_client.get(
                f"https://{gateway}:19999/bindPort",
                params={
                    "payload": payload,
                    "signature": signature,
                },
            )
        response.raise_for_status()
        obj = response.json()
        status = obj["status"]
        message = obj["message"]
        if status != "OK":
            raise Exception(
                f"Unable to bind port! (status={status}, message={message})"
            )