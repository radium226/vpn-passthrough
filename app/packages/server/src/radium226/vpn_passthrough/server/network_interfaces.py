import asyncio
import hashlib
import ipaddress
from contextlib import asynccontextmanager
from typing import AsyncIterator

from radium226.vpn_passthrough.netns_native import netns_native

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
    async def add(namespace: Namespace, veth_ip: str | None = None, vpeer_ip: str | None = None, cidr: str | None = None, extra_routes: list[str] | None = None) -> AsyncIterator["NetworkInterfaces"]:
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

        # Create the veth pair, configure both ends, and move the peer into
        # the namespace — all via netlink (see the netns-native package)
        # rather than shelling out to `ip`.
        await asyncio.to_thread(
            netns_native.add_veth_pair,
            veth=veth,
            vpeer=vpeer,
            veth_ip=resolved_veth_ip,
            vpeer_ip=resolved_vpeer_ip,
            prefix_len=prefix_len,
            netns_pid=namespace.pid,
            extra_routes=extra_routes or [],
        )
        try:
            yield NetworkInterfaces(name, veth, vpeer, resolved_veth_ip, resolved_vpeer_ip, prefix_len)
        finally:
            # Deleting the host end also removes its peer.
            await asyncio.to_thread(netns_native.delete_link, veth)
