from pathlib import Path

from .netns import NetNS


def setup_dns(nameserver_ip_addr: str, netns: NetNS) -> None:
    resolv_conf_file_path = Path("/etc/netns") / netns.name / "resolv.conf"
    resolv_conf_file_path.parent.mkdir(parents=True, exist_ok=True)
    resolv_conf_file_path.write_text(f"nameserver {nameserver_ip_addr}")
    