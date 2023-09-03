from subprocess import run

from ..network_namespace import NetworkNamespace
from .strategy import Strategy


def find_ip(*, strategy: Strategy = Strategy.HTTP, network_namespace: NetworkNamespace | None = None) -> str:

    match strategy:
        case Strategy.HTTP:
            ip_command_part = ["sudo", "ip", "netns", "exec", network_namespace.name] if network_namespace else []
            curl_command_part = ["curl", "-s", "https://api.ipify.org?format=text"]
            command = ip_command_part + curl_command_part

            return run(command, capture_output=True, check=True, text=True).stdout.strip()

        case Strategy.TORRENT:
            raise Exception("Not yet implemented! ")