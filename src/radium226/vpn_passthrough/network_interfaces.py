from typing import Generator
from contextlib import contextmanager
from loguru import logger
from dataclasses import dataclass
from loguru import logger
from subprocess import run
from pathlib import Path

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
        


@contextmanager
def create_network_interfaces(
    netns: NetNS,
    vpeer: VPeer,
    veth: VEth,
) -> Generator[NetworkInterfaces, None, None]:
    logger.debug(f"Creating network interfaces...")

    run(["ip", "link", "add", veth.name, "type", "veth", "peer", "name", vpeer.name, "netns", netns.name], check=True)
    run(["ip", "addr", "add", f"{veth.addr}/24", "dev", veth.name], check=True)
    run(["ip", "link", "set", veth.name, "up"], check=True)

    run(["ip", "netns", "exec", netns.name, "ip", "addr", "add", f"{vpeer.addr}/24", "dev", vpeer.name], check=True)
    run(["ip", "netns", "exec", netns.name, "ip", "link", "set", vpeer.name, "up"], check=True)

    run(["ip", "netns", "exec", netns.name, "ip", "link", "set", "lo", "up"], check=True)

    run(["ip", "netns", "exec", netns.name, "ip", "route", "add", "default", "via", veth.addr], check=True)

    try:
        yield NetworkInterfaces(
            netns=netns,
            veth=veth,
            vpeer=vpeer,
        )
    finally:
        run(["ip", "link", "delete", veth.name], check=True)