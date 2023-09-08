from dataclasses import dataclass
from typing import ClassVar, NewType, Protocol, Any
from subprocess import run, Popen, PIPE, DEVNULL
from textwrap import dedent
from pathlib import Path
from enum import Enum, auto
from io import BytesIO
import dill


NetworkNamespaceName = NewType("NetworkNamespaceName", str)


class Func(Protocol):

    def __call__(**kwargs: dict[str, Any]) -> Any:
        pass


@dataclass
class NetworkNamespace:

    name: NetworkNamespaceName

    VPEER_IFACE: ClassVar[str] = "vpeer1"
    VPEER_ADDR: ClassVar[str] = "10.200.1.1"
    
    VETH_IFACE: ClassVar[str] = "veth1"
    VETH_ADDR: ClassVar[str] = "10.200.1.2"

    @staticmethod
    def current() -> "NetworkNamespace":
        command = ["sudo", "ip", "netns", "id"]
        name = run(command, text=True, capture_output=True, check=True).stdout.strip()
        return NetworkNamespace(name=name)
    

    def exec(self, command: list[str], **kwargs):
        run(["sudo", "ip", "netns", "exec", self.name] + command, **kwargs)

    def attach(self, func: Func) -> Func:
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
            output_bytes = run(command, input=input_bytes, check=True, capture_output=True).stdout
            output_payload = dill.loads(output_bytes)
            return output_payload

        return closure

    def __enter__(self) -> "NetworkNamespace":

        write_file(
            dedent("""\
            nameserver 208.67.222.222
            nameserver 208.67.220.220
            """),
            Path("/etc/netns") / self.name / "resolv.conf"
        )

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

        nftables_conf_file_path = Path(__file__).parent / "nftables.conf"
        run(["sudo", "nft", "--file", str(nftables_conf_file_path), "--define", f"veth_iface={NetworkNamespace.VETH_IFACE}"], check=True)
        
        return self

    def __exit__(self, type, value, traceback):
        run(["sudo", "ip", "link", "del", NetworkNamespace.VETH_IFACE], check=True)
        run(["sudo", "ip", "netns", "del", self.name], check=True)


def write_file(content: str, file_path: Path):
    run(["sudo", "mkdir", "-p", str(file_path.parent)], check=True)
    tee_process = Popen(["sudo", "tee", str(file_path)], stdin=PIPE, stdout=DEVNULL, text=True)
    if stdin := tee_process.stdin:
        stdin.write(content)
        stdin.close()
    tee_process.wait()


def list_network_namespaces() -> list[NetworkNamespace]:
    return [
        NetworkNamespace(NetworkNamespaceName(name))
        for name in run(["sudo", "ip", "netns", "show"], capture_output=True, text=True, check=True).stdout.splitlines()
    ]