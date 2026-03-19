import hashlib
import ipaddress
from contextlib import asynccontextmanager
from typing import AsyncIterator

from ._run import run
from .namespace import Namespace


class NetworkInterfaces:
    def __init__(self, name: str, veth: str, vpeer: str, veth_ip: str, vpeer_ip: str, prefix_len: int) -> None:
        self._name = name
        self._veth = veth
        self._vpeer = vpeer
        self._veth_ip = veth_ip
        self._vpeer_ip = vpeer_ip
        self._prefix_len = prefix_len

    @property
    def veth(self) -> str:
        return self._veth

    @property
    def vpeer(self) -> str:
        return self._vpeer

    @property
    def veth_ip(self) -> str:
        return self._veth_ip

    @property
    def vpeer_ip(self) -> str:
        return self._vpeer_ip

    @property
    def subnet(self) -> str:
        """Return the network subnet in CIDR notation (e.g. ``10.200.5.0/24``)."""
        return str(ipaddress.IPv4Interface(f"{self._veth_ip}/{self._prefix_len}").network)

    @staticmethod
    @asynccontextmanager
    async def add(namespace: Namespace, veth_ip: str | None = None, vpeer_ip: str | None = None, cidr: str | None = None) -> AsyncIterator["NetworkInterfaces"]:
        name = namespace.name
        slot = int(hashlib.md5(name.encode()).hexdigest()[:4], 16) % 254 + 1

        if cidr is not None:
            network = ipaddress.IPv4Network(cidr, strict=False)
            hosts = list(network.hosts())
            resolved_veth_ip = str(hosts[1])
            resolved_vpeer_ip = str(hosts[0])
            prefix_len = network.prefixlen
        else:
            resolved_veth_ip = veth_ip or f"10.200.{slot}.2"
            resolved_vpeer_ip = vpeer_ip or f"10.200.{slot}.1"
            prefix_len = 24

        # Interface names are capped at 15 chars (IFNAMSIZ-1); use slot-based names
        veth = f"vpt{slot}v"
        vpeer = f"vpt{slot}p"

        # Create veth pair in host namespace, then move peer into the namespace by PID
        await run(["ip", "link", "add", veth, "type", "veth", "peer", "name", vpeer], check=True)
        try:
            await run(["ip", "link", "set", vpeer, "netns", str(namespace.pid)], check=True)

            # Configure host side
            await run(["ip", "addr", "add", f"{resolved_veth_ip}/{prefix_len}", "dev", veth], check=True)
            await run(["ip", "link", "set", veth, "up"], check=True)

            # Configure namespace side
            await run(["ip", "addr", "add", f"{resolved_vpeer_ip}/{prefix_len}", "dev", vpeer], check=True, preexec_fn=namespace.enter)
            await run(["ip", "link", "set", vpeer, "up"], check=True, preexec_fn=namespace.enter)
            await run(["ip", "link", "set", "lo", "up"], check=True, preexec_fn=namespace.enter)
            await run(["ip", "route", "add", "default", "via", resolved_veth_ip], check=True, preexec_fn=namespace.enter)

            yield NetworkInterfaces(name, veth, vpeer, resolved_veth_ip, resolved_vpeer_ip, prefix_len)
        finally:
            await run(["ip", "link", "delete", veth])
