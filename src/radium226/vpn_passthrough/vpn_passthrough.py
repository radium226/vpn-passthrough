from dataclasses import dataclass, field
from typing import Generator
from contextlib import (
    ExitStack,
    contextmanager,
)
from loguru import logger
from .netns import create_netns, NetNS
from .network_interfaces import create_network_interfaces, VEth, VPeer
from .internet import share_internet
from .openvpn import start_openvpn
from .pia import Region, Credentials, NAMESERVER_IP_ADDR
from .dns import setup_dns
from .pipewire import bind_pipewire



@dataclass
class VPNPassthrough:
    
    name: str
    netns: NetNS
    veth: VEth
    
    def exec(self, command: list[str]) -> None:
        logger.debug(f"Executing command in VPNPassthrough {self.name}: {command}")
        self.netns.exec(command)



@contextmanager
def open_vpn_passthrough(
    name: str, 
    pia_region: Region,
    pia_credentials: Credentials,
) -> Generator[VPNPassthrough, None, None]:
    exit_stack = ExitStack()
    try:
        veth = VEth(name=f"{name}-veth", addr="10.200.1.2")
        vpeer = VPeer(name=f"{name}-vpeer", addr="10.200.1.1")

        netns = exit_stack.enter_context(create_netns(name))
        network_interfaces = exit_stack.enter_context(create_network_interfaces(
            netns=netns, 
            vpeer=vpeer, 
            veth=veth,
        ))

        exit_stack.enter_context(share_internet(
            name=name, 
            network_interfaces=network_interfaces, 
        ))

        exit_stack.enter_context(start_openvpn(
            netns=netns,
            pia_region=pia_region,  
            pia_credentials=pia_credentials,
        ))

        setup_dns(
            NAMESERVER_IP_ADDR,
            netns=netns,
        )

        yield VPNPassthrough(
            name=name, 
            netns=netns, 
            veth=veth,
        )
    finally:
        exit_stack.close()