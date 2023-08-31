from dataclasses import dataclass
from typing import ClassVar
from subprocess import run


@dataclass
class NetworkNamespace:

    name: str

    VPEER_IFACE: ClassVar[str] = "vpeer1"
    VPEER_ADDR: ClassVar[str] = "10.200.1.1"
    
    VETH_IFACE: ClassVar[str] = "veth1"
    VETH_ADDR: ClassVar[str] = "10.200.1.2"

    def exec(self, command: list[str], **kwargs):
        run(["sudo", "ip", "netns", "exec", self.name] + command, **kwargs)

    def __enter__(self) -> "NetworkNamespace":
        # Create the namespace
        run(["sudo", "ip", "netns", "add", self.name], check=True)
        
        # Create the veth link and put the peer in the namespace
        run(["sudo", "ip", "link", "add", NetworkNamespace.VETH_IFACE, "type", "veth", "peer", "name", NetworkNamespace.VPEER_IFACE, "netns", self.name], check=True)
        
        # Setup IP address of veth side
        run(["sudo", "ip", "addr", "add", f"{NetworkNamespace.VETH_ADDR}/24", "dev", NetworkNamespace.VETH_IFACE], check=True)
        run(["sudo", "ip", "link", "set", NetworkNamespace.VETH_IFACE, "up"], check=True)

        # Setup address of vpeer side within namespace
        self.exec(["ip", "addr", "add", f"{NetworkNamespace.VPEER_ADDR}/24", "dev", NetworkNamespace.VPEER_IFACE], check=True)
        self.exec(["ip", "link", "set", NetworkNamespace.VPEER_IFACE, "up"], check=True)
        
        # Setup loopback within namespace
        self.exec(["ip", "link", "set", "lo", "up"], check=True)
        self.exec(["ip", "route", "add", "default", "via", NetworkNamespace.VETH_ADDR], check=True)
        
        return self

    def __exit__(self, type, value, traceback):
        run(["sudo", "ip", "netns", "del", self.name], check=True)


def list_network_namespaces() -> list[NetworkNamespace]:
    return [
        NetworkNamespace(name)
        for name in run(["sudo", "ip", "netns", "show"], capture_output=True, text=True, check=True).stdout.splitlines()
    ]