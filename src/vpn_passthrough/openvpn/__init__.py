from typing import ClassVar
from pathlib import Path
from dataclasses import dataclass
from subprocess import Popen, run
from time import sleep
from os import environ, chmod
from shutil import which

from ..network_namespace import NetworkNamespace
from ..commons import Credentials
from .script import ScriptServer

@dataclass
class Tunnel():

    gateway: str


@dataclass
class OpenVPN:

    # country: str = "serbia"
    # config_folder_path: Path | None = None

    config_file_path: Path

    remote: str | None = None

    ca_pem_file_path: Path | None = None

    network_namespace: NetworkNamespace | None = None

    credentials: Credentials | None = None

    port: int | None = None

    CONFIG_FOLDER_PATH: ClassVar[Path] = Path("./openvpn")
    TUNNEL_IFACE: ClassVar[str] = "tun0"

    _process: Popen | None = None
    _script_server: ScriptServer | None = None



    def __enter__(self):
        tunnel = self.open_tunnel()
        return tunnel

    def open_tunnel(self) -> Tunnel:
        sudo_command_part = ["sudo", "-E"]

        ip_command_part = ["ip", "netns", "exec", network_namespace.name] if (network_namespace := self.network_namespace) else []


        script_socket_path = Path("/tmp/vpn-passthrough-openvpn-script.sock")
        script_server = ScriptServer(socket_path=script_socket_path)
        script_server.start()
        self._script_server = script_server
    
        auth_pass_file_path: Path | None = None
        if self.credentials:
            auth_pass_file_path = Path("/tmp/pass.txt")
            with auth_pass_file_path.open("w") as f:
                f.write(f"{self.credentials.user}\n{self.credentials.password}\n")
                chmod(auth_pass_file_path, 0o600)

        
        if not (script_path := which("vpn-passthrough-openvpn-script")):
            raise Exception("Unable to find the script! ")

        openvpn_command_part = (
            [
                "openvpn",
                    "--verb", "0",
                    "--config", str(self.config_file_path),
                    "--dev", OpenVPN.TUNNEL_IFACE,
                    "--errors-to-stderr",
                    "--pull-filter", "ignore", "route-ipv6",
                    "--pull-filter", "ignore", "ifconfig-ipv6",
                    "--script-security", "2", \
                    "--setenv", "NEW_NAMESERVER", "10.0.0.242",
                    "--setenv", "OLD_NAMESERVER", "208.67.222.222",
                    "--setenv", "script_socket_path", "208.67.222.222",
                    "--setenv", "PATH", environ["PATH"],
                    "--up", script_path,
                    "--down", script_path,
            ] + 
            # (["--ca", str(ca_pem_file_path)] if (ca_pem_file_path := self.ca_pem_file_path) else []) + 
            (["--remote", str(remote)] if (remote := self.remote) else []) +
            (["--auth-user-pass", str(file_path)] if (file_path := auth_pass_file_path) else []) +
            (["--port", str(port)] if (port := self.port) else [])
        )

        command = sudo_command_part + ip_command_part + openvpn_command_part
        self._process = Popen(command, env=environ | {"PATH": environ["PATH"]})

        up_info = script_server.wait_for_up()
        gateway = up_info["route_vpn_gateway"]

        return Tunnel(
            gateway=gateway,
        )

    def close_tunnel(self) -> None:
        if (process := self._process) and (script_server := self._script_server):
            run(["kill", "-s", "TERM", str(process.pid)])
            self.wait()
            script_server.stop()
        else:
            raise Exception("OpenVPN is not started! ")

    def __exit__(self, type, value, traceback):
        self.close_tunnel()

    def wait(self):
        if (process := self._process):
            process.wait()
        else:
            raise Exception("OpenVPN is not started! ")