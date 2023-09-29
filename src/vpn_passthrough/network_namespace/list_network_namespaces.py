from subprocess import run

from .network_namespace_name import NetworkNamespaceName
from .network_namespace import NetworkNamespace

def list_network_namespaces() -> list[NetworkNamespace]:
    return [
        NetworkNamespace(NetworkNamespaceName(name))
        for name in run(["sudo", "ip", "netns", "show"], capture_output=True, text=True, check=True).stdout.splitlines()
    ]