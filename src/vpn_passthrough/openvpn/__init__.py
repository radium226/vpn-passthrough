from typing import ClassVar
from pathlib import Path
from dataclasses import dataclass
from subprocess import Popen, run
from time import sleep

from ..network_namespace import NetworkNamespace
from .script import ScriptServer

@dataclass
class Tunnel():

    gateway: str


@dataclass
class OpenVPN:

    country: str = "serbia"
    config_folder_path: Path | None = None

    network_namespace: NetworkNamespace | None = None

    CONFIG_FOLDER_PATH: ClassVar[Path] = Path("./openvpn")
    TUNNEL_IFACE: ClassVar[str] = "tun0"

    _process: Popen | None = None



    def __enter__(self):
        tunnel = self.open_tunnel()
        return tunnel

    def open_tunnel(self) -> Tunnel:
        config_folder_path = self.config_folder_path or OpenVPN.CONFIG_FOLDER_PATH
        config_file_path = Path(f"{self.country}.ovpn")

        sudo_command_part = ["sudo", "-E"]

        ip_command_part = ["ip", "netns", "exec", network_namespace.name] if (network_namespace := self.network_namespace) else []


        script_socket_path = Path("/tmp/vpn-passthrough-openvpn-script.sock")
        script_server = ScriptServer(socket_path=script_socket_path)
        script_server.start()

        openvpn_command_part = [
            "openvpn",
                "--cd", str(config_folder_path),
                "--config", str(config_file_path),
                "--dev", OpenVPN.TUNNEL_IFACE,
                "--auth-user-pass", "pass.txt",
                "--errors-to-stderr",
                "--pull-filter", "ignore", "route-ipv6",
                "--pull-filter", "ignore", "ifconfig-ipv6",
                "--script-security", "2", \
                "--setenv", "NEW_NAMESERVER", "10.0.0.242",
                "--setenv", "OLD_NAMESERVER", "208.67.222.222",
                "--setenv", "script_socket_path", "208.67.222.222",
                "--up", "vpn-passthrough-openvpn-script",
                "--down", "vpn-passthrough-openvpn-script",
        ]

        command = sudo_command_part + ip_command_part + openvpn_command_part
        self._process = Popen(command)

        up_info = script_server.wait_for_up()
        gateway = up_info["route_vpn_gateway"]

        return Tunnel(
            gateway=gateway,
        )

    def close_tunnel(self) -> None:
        if (process := self._process):
            run(["kill", "-s", "TERM", str(process.pid)])
        else:
            raise Exception("OpenVPN is not started! ")

    def __exit__(self, type, value, traceback):
        self.close_tunnel()

    def wait(self):
        if (process := self._process):
            process.wait()
        else:
            raise Exception("OpenVPN is not started! ")