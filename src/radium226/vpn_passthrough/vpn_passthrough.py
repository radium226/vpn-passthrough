from dataclasses import dataclass, field
from typing import Generator
from contextlib import (
    ExitStack,
    contextmanager,
)
from loguru import logger
from .netns import create_netns, NetNS
from .network_interfaces import create_network_interfaces, VEth, VPeer
from .port_forwarding import start_port_forwarding, PortForwarding
from .internet import share_internet



@dataclass
class VPNPassthrough:
    
    name: str
    netns: NetNS
    veth: VEth
    port_forwarding: PortForwarding
    
    def exec(self, command: list[str]) -> None:
        logger.debug(f"Executing command in VPNPassthrough {self.name}: {command}")
        self.netns.exec(command)



@contextmanager
def open_vpn_passthrough(name: str) -> Generator[VPNPassthrough, None, None]:
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
            netns=netns,
        ))


        port_forwarding = exit_stack.enter_context(start_port_forwarding())
        yield VPNPassthrough(
            name=name, 
            netns=netns, 
            veth=veth,
            port_forwarding=port_forwarding,
        )
    finally:
        exit_stack.close()