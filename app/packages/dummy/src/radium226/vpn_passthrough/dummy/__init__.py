from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import AsyncIterator

from radium226.vpn_passthrough.vpn import Region, Session


class DummyBackend:

    @asynccontextmanager
    async def connect(
        self,
        netns_name: str,
        *,
        enter_namespace: Callable[[], None],
        credentials: dict[str, str],
        region_id: str,
    ) -> AsyncIterator[Session]:
        @asynccontextmanager
        async def _forward_port() -> AsyncIterator[int]:
            yield 0

        yield Session(
            gateway_ip="10.0.0.1",
            tun_ip="10.8.0.2",
            dns_servers=["10.0.0.1"],
            forward_port=_forward_port,
        )

    async def list_regions(self) -> list[Region]:
        return [
            Region(id="dummy", name="Dummy", country="XX", port_forward=True),
        ]
