import hashlib
from contextlib import asynccontextmanager
from typing import AsyncIterator

from ._run import run
from .namespace import Namespace


class NetworkInterfaces:
    def __init__(self, name: str, veth: str, vpeer: str, veth_addr: str, vpeer_addr: str) -> None:
        self._name = name
        self._veth = veth
        self._vpeer = vpeer
        self._veth_addr = veth_addr
        self._vpeer_addr = vpeer_addr

    @property
    def veth(self) -> str:
        return self._veth

    @property
    def vpeer(self) -> str:
        return self._vpeer

    @property
    def veth_addr(self) -> str:
        return self._veth_addr

    @property
    def vpeer_addr(self) -> str:
        return self._vpeer_addr

    @staticmethod
    @asynccontextmanager
    async def add(namespace: Namespace, veth_addr: str | None = None, vpeer_addr: str | None = None) -> AsyncIterator["NetworkInterfaces"]:
        name = namespace.name
        slot = int(hashlib.md5(name.encode()).hexdigest()[:4], 16) % 254 + 1
        resolved_veth_addr = veth_addr or f"10.200.{slot}.2"
        resolved_vpeer_addr = vpeer_addr or f"10.200.{slot}.1"
        # Interface names are capped at 15 chars (IFNAMSIZ-1); use slot-based names
        veth = f"vpt{slot}v"
        vpeer = f"vpt{slot}p"

        # Create veth pair in host namespace, then move peer into the namespace by PID
        await run(["ip", "link", "add", veth, "type", "veth", "peer", "name", vpeer], check=True)
        try:
            await run(["ip", "link", "set", vpeer, "netns", str(namespace.pid)], check=True)

            # Configure host side
            await run(["ip", "addr", "add", f"{resolved_veth_addr}/24", "dev", veth], check=True)
            await run(["ip", "link", "set", veth, "up"], check=True)

            # Configure namespace side
            await run(["ip", "addr", "add", f"{resolved_vpeer_addr}/24", "dev", vpeer], check=True, preexec_fn=namespace.enter)
            await run(["ip", "link", "set", vpeer, "up"], check=True, preexec_fn=namespace.enter)
            await run(["ip", "link", "set", "lo", "up"], check=True, preexec_fn=namespace.enter)
            await run(["ip", "route", "add", "default", "via", resolved_veth_addr], check=True, preexec_fn=namespace.enter)

            yield NetworkInterfaces(name, veth, vpeer, resolved_veth_addr, resolved_vpeer_addr)
        finally:
            await run(["ip", "link", "delete", veth])
