from typing import Self, AsyncGenerator
from contextlib import asynccontextmanager
from loguru import logger
from dataclasses import dataclass


from ...shared.subprocess import run

from .netns import NetNS


@dataclass
class VEth:
    
    name: str
    addr: str



@dataclass
class VPeer:

    name: str
    addr: str



@dataclass
class NetworkInterfaces:

    netns: NetNS
    veth: VEth
    vpeer: VPeer


    @classmethod
    @asynccontextmanager
    async def add(cls, netns: NetNS, vpeer: VPeer, veth: VEth) -> AsyncGenerator[Self, None]:
        logger.debug("Adding network interfaces...")

        await run(["ip", "link", "add", veth.name, "type", "veth", "peer", "name", vpeer.name, "netns", netns.name], check=True)
        await run(["ip", "addr", "add", f"{veth.addr}/24", "dev", veth.name], check=True)
        await run(["ip", "link", "set", veth.name, "up"], check=True)

        await run(["ip", "netns", "exec", netns.name, "ip", "addr", "add", f"{vpeer.addr}/24", "dev", vpeer.name], check=True)
        await run(["ip", "netns", "exec", netns.name, "ip", "link", "set", vpeer.name, "up"], check=True)
        
        await run(["ip", "netns", "exec", netns.name, "ip", "link", "set", "lo", "up"], check=True)

        await run(["ip", "netns", "exec", netns.name, "ip", "route", "add", "default", "via", veth.addr], check=True)

        try:
            yield cls(
                netns=netns,
                veth=veth,
                vpeer=vpeer,
            )
        finally:
            logger.debug("Deleting network interfaces...")
            await run(["ip", "link", "delete", veth.name], check=True)