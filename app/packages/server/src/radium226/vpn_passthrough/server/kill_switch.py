import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

from loguru import logger

from radium226.vpn_passthrough.nftables_native import nftables_native

from .network_interfaces import NetworkInterfaces


class KillSwitch:

    @staticmethod
    @asynccontextmanager
    async def activate(
        ni: NetworkInterfaces,
        server_ip: str,
        extra_routes: list[str] | None = None,
    ) -> AsyncIterator[None]:
        table_name = f"kill_switch_{ni.veth}"

        await asyncio.to_thread(
            nftables_native.install_kill_switch,
            table_name=table_name,
            veth=ni.veth,
            server_ip=server_ip,
            extra_routes=extra_routes or [],
        )
        logger.info("Kill switch activated for {} (allow {})", ni.veth, server_ip)

        try:
            yield
        finally:
            await asyncio.to_thread(nftables_native.delete_table, table_name)
            logger.info("Kill switch deactivated for {}", ni.veth)
