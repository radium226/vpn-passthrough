from dataclasses import dataclass
from typing import ClassVar, NewType, Protocol, Any
from subprocess import run, Popen, PIPE, DEVNULL
from textwrap import dedent
from pathlib import Path
from enum import Enum, auto
from io import BytesIO
from ipaddress import IPv4Address
import dill

from ..nftables import nftables
from ..sudo import sudo

from .network_namespace_name import NetworkNamespaceName



class Func(Protocol):

    def __call__(**kwargs: dict[str, Any]) -> Any:
        pass


@dataclass
class NetworkNamespace:

    name: NetworkNamespaceName

    VPEER_IFACE: ClassVar[str] = "vpeer1"
    VPEER_ADDR: ClassVar[IPv4Address] = IPv4Address("10.200.1.1")
    
    VETH_IFACE: ClassVar[str] = "veth1"
    VETH_ADDR: ClassVar[IPv4Address] = IPv4Address("10.200.1.2")

    NAMESERVER_IP_ADDRESSES: ClassVar[list[IPv4Address]] = [
        IPv4Address("208.67.222.222"),
        IPv4Address("208.67.220.220"),
    ] 

    @staticmethod
    def current() -> "NetworkNamespace":
        command = ["sudo", "ip", "netns", "id"]
        name = run(command, text=True, capture_output=True, check=True).stdout.strip()
        return NetworkNamespace(name=NetworkNamespaceName(name))
    

    def exec(self, command: list[str], **kwargs):
        run(["sudo", "ip", "netns", "exec", self.name] + command, **kwargs)

    def attach(self, func: Func, capture_output: bool = True) -> Func:
        def closure(*args, **kwargs):
            input_payload = {
                "func": func,
                "args": args,
                "kwargs": kwargs,
            }
            input_bytes = dill.dumps(input_payload)

            ip_command_part = ["sudo", "ip", "netns", "exec", str(self.name)]
            python_command_part = ["python", "-m", "vpn_passthrough.network_namespace"]
            command = ip_command_part + python_command_part
            process = run(command, input=input_bytes, check=True, capture_output=capture_output)
            if capture_output:
                output_bytes = process.stdout
                output_payload = dill.loads(output_bytes)
                return output_payload
            else:
                return None

        return closure

    def __enter__(self) -> "NetworkNamespace":
        self._write_resolv_conf_file(ip_addresses=NetworkNamespace.NAMESERVER_IP_ADDRESSES)
        self._setup_netns()
        self._forward_traffic(veth_iface=NetworkNamespace.VETH_IFACE)
        return self

    def __exit__(self, type, value, traceback):
        self._teardown_netns()

    def _teardown_netns(self) -> None:
        run(["sudo", "ip", "link", "del", NetworkNamespace.VETH_IFACE], check=True)
        run(["sudo", "ip", "netns", "del", self.name], check=True)

    def _setup_netns(self) -> None:
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
        self.exec(["ip", "route", "add", "default", "via", f"{NetworkNamespace.VETH_ADDR}"], check=True)

    @sudo()
    def _write_resolv_conf_file(self, ip_addresses: list[IPv4Address]) -> None:
        resolv_conf_file_path = Path("/etc/netns") / self.name / "resolv.conf"
        resolv_conf_file_path.parent.mkdir(parents=True, exist_ok=True)
        with resolv_conf_file_path.open("w") as f:
            for ip_address in ip_addresses:
                f.write(f"nameserver {ip_address}\n")

    @nftables()
    def _forward_traffic(self, veth_iface: str) -> None:
        """
            table inet filter {
                chain forward {
                    type filter hook forward priority 0; policy accept;
                    iifname $veth_iface counter accept;
                    oifname $veth_iface counter accept;
                }
            }

            # Postrouting masquerade
            table inet nat {
                chain prerouting {
                    type nat hook prerouting priority dstnat; policy accept;
                }
                chain postrouting {
                    type nat hook postrouting priority srcnat; policy accept;
                    masquerade random
                }
            }
        """