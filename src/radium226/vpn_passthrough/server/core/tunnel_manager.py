from typing import Self, AsyncGenerator
import asyncio
from loguru import logger
from contextlib import AsyncExitStack
from enum import StrEnum, auto
from httpx import AsyncClient


from ...shared.pia import (
    Region,
    PIA,
)

from .netns import NetNS

from contextlib import asynccontextmanager

from .tunnel import Tunnel
from .network_interfaces import VEth, VPeer, NetworkInterfaces
from .internet import Internet
from .openvpn import OpenVPN, OpenVPNConfig, OpenVPNAuth
from .dns import DNS



NAMESERVER_IP_ADDR = "10.0.0.242"


class TestMode(StrEnum):

    UNIT = auto()
    E2E = auto()



class TunnelManager():

    _pia: PIA

    _test_mode: TestMode | None = None


    def __init__(self, pia: PIA, test_mode: TestMode | None = None):
        self._pia = pia
        self._test_mode = test_mode


    @classmethod
    @asynccontextmanager
    async def create(cls, pia: PIA, test_mode: TestMode | None = None) -> AsyncGenerator[Self, None]:
        instance = cls(pia, test_mode)
        try:
            yield instance
        finally:
            await instance.destroy()

    async def destroy(self) -> None:
        pass

    async def list_regions(self) -> list[Region]:
        return await self._pia.list_regions()
    

    @asynccontextmanager
    async def open_tunnel(
        self,
        name: str,  
        region: Region,

    ) -> AsyncGenerator[Tunnel, None]:
        logger.debug("Opening tunnel... (name={name}, region.id={region.id})", name=name, region=region)
        exit_stack = AsyncExitStack()
        try:
            if self._test_mode is not TestMode.UNIT:
                netns = await exit_stack.enter_async_context(NetNS.create(name))

                veth = VEth(name=f"{name}-veth", addr="10.200.1.2")
                vpeer = VPeer(name=f"{name}-vpeer", addr="10.200.1.1")
                network_interfaces = await exit_stack.enter_async_context(NetworkInterfaces.add(
                    netns=netns, 
                    vpeer=vpeer, 
                    veth=veth,
                ))

                # TODO: Fix this by defining a proper way to choose the server
                if not ( server := next(iter(region.servers.ovpnudp), None)):
                    raise RuntimeError(f"No servers available for region {region.id}")

                # TODO: We should have a utils or tools module with a netns param
                server_ip = server.ip

                await exit_stack.enter_async_context(Internet.share(
                    name=name, 
                    network_interfaces=network_interfaces,
                    server_ip=server_ip,
                ))
            
                result = await netns.ping(server_ip)
                assert result.packet_loss_ratio < 0.25, f"High packet loss when pinging server {server_ip} in NetNS {netns.name}"

                result = await netns.ping("8.8.8.8")
                assert result.packet_loss_ratio == 1.0, f"Internet connectivity is not bound to PIA server {server_ip} in NetNS {netns.name}"

                await exit_stack.enter_async_context(OpenVPN.start(
                    OpenVPNConfig(
                        proto="udp",
                        auth=OpenVPNAuth(
                            user=self._pia.credentials.user,
                            password=self._pia.credentials.password,
                        ),
                        remote=server_ip,
                        port=1198,
                    ),
                    netns=netns,
                ))

                await exit_stack.enter_async_context(DNS.setup(NAMESERVER_IP_ADDR, netns))

                for i in range(5):
                    try:
                        # FIXME: Use tenacity instead
                        await asyncio.sleep(2)  # Wait for DNS to be set up

                        result = await netns.ping("www.google.com")
                        assert result.packet_loss_ratio == 0, f"DNS is not working! (packet_loss_ratio={result.packet_loss_ratio})"
                        break
                    except Exception as e:
                        if i < 5:
                            continue
                        else:
                            raise e
                logger.info("IP inside the tunnel is {ip}", ip=veth.addr)
                logger.info("IP outside the tunnel is {ip}", ip=vpeer.addr)
            else:
                netns = None
                logger.warning("Skipping network setup as we're in TestMode.UNIT... Wait 5 seconds instead! ")
                await asyncio.sleep(5)

            http_client = await exit_stack.enter_async_context(AsyncClient())

            tunnel = Tunnel(
                name=name,
                region=region,
                netns=netns,
                http_client=http_client,
                pia=self._pia,
            )

            tunnel_info = await tunnel.lookup_info()
            tunnel_ip = tunnel_info.ip
            logger.info("WAN IP is: {tunnel_ip}", tunnel_ip=tunnel_ip)

            if self._test_mode is None or self._test_mode is TestMode.E2E:
                port = await tunnel.forward_port()
                logger.info("Forwareded port: {port}", port=port)

            logger.debug("Yielding tunnel...")
            yield tunnel
        except Exception as e:
            logger.error(f"Failed to open tunnel: {e}")
            raise
        finally:
            await exit_stack.aclose()