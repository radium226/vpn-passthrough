from typing import ClassVar
from pathlib import Path
from dataclasses import dataclass
from subprocess import Popen, run

from ..network_namespace import NetworkNamespace


@dataclass
class OpenVPN:

    country: str = "serbia"
    config_folder_path: Path | None = None

    network_namespace: NetworkNamespace | None = None

    CONFIG_FOLDER_PATH: ClassVar[Path] = Path("./openvpn")
    TUNNEL_IFACE: ClassVar[str] = "tun0"

    _process: Popen | None = None

    def __enter__(self):
        self.start()

    def start(self) -> None:
        config_file_path = (self.config_folder_path or OpenVPN.CONFIG_FOLDER_PATH) / f"{self.country}.conf"

        sudo_command_part = ["sudo"]

        ip_command_part = ["ip", "netns", "exec", network_namespace.name] if (network_namespace := self.network_namespace) else []

        openvpn_command = [
            "openvpn",
                "--cd", str(OpenVPN.CONFIG_FOLDER_PATH),
                "--config", str(config_file_path),
                "--dev", OpenVPN.TUNNEL_IFACE,
                "--errors-to-stderr"
        ]

        command = sudo_command_part + ip_command_part + openvpn_command_part

        self._process = Popen(command)

    def stop(self) -> None:
        if (process := self._process):
            run(["kill", "-s", "TERM", str(process.pid)])
        else:
            raise Exception("OpenVPN is not started! ")

    def __exit__(self, type, value, traceback):
        self.stop()

    def wait(self):
        if (process := self._process):
            process.wait()
        else:
            raise Exception("OpenVPN is not started! ")