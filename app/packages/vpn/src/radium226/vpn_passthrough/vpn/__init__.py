from contextlib import AbstractAsyncContextManager
from collections.abc import Callable
from dataclasses import dataclass
from importlib.metadata import entry_points
from typing import Protocol


@dataclass(frozen=True)
class Region:
    id: str
    name: str
    country: str
    port_forward: bool = False


@dataclass(frozen=True)
class Session:
    gateway_ip: str
    tun_ip: str
    dns_servers: tuple[str, ...]
    forwarded_ports: tuple[int, ...]
    forward_port: Callable[[], AbstractAsyncContextManager[int]]


class Backend(Protocol):
    def connect(
        self,
        netns_name: str,
        *,
        enter_netns: Callable[[], None],
        credentials: dict[str, str],
        region_id: str,
        forwarded_port_count: int = 0,
    ) -> AbstractAsyncContextManager[Session]: ...

    async def list_regions(self) -> list[Region]: ...


_ENTRY_POINT_GROUP = "vpn_passthrough.vpn_backends"


def get_backend(name: str) -> Backend:
    """Load a VPN backend by name from entry_points group 'vpn_passthrough.vpn_backends'."""
    eps = entry_points(group=_ENTRY_POINT_GROUP, name=name)
    for ep in eps:
        cls = ep.load()
        return cls()
    available = list_backends()
    raise LookupError(
        f"VPN backend {name!r} not found. Available backends: {available}"
    )


def list_backends() -> list[str]:
    """List available backend names."""
    return [ep.name for ep in entry_points(group=_ENTRY_POINT_GROUP)]
