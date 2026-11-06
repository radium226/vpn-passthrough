import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

from loguru import logger

from ._run import run
from .network_interfaces import NetworkInterfaces


def _table_name(ni: NetworkInterfaces) -> str:
    return f"kill_switch_{ni.veth}"


class KillSwitch:

    @staticmethod
    async def clear_stale(ni: NetworkInterfaces) -> None:
        """Remove the kill switch a former tunnel left on the veth, which a new tunnel on the same veth gets, when it
        died without deactivating it: it would only let the tunnel reach the VPN server of the former one."""
        await run(["nft", "destroy", "table", "inet", _table_name(ni)])

    @staticmethod
    @asynccontextmanager
    async def activate(
        ni: NetworkInterfaces,
        server_ip: str,
        extra_routes: list[str] | None = None,
    ) -> AsyncIterator[None]:
        table_name = _table_name(ni)
        extra_accept_rules = "".join(
            f'        iifname "{ni.veth}" ip daddr {route} accept\n'
            for route in (extra_routes or [])
        )
        # Replacing whatever a former tunnel left, rather than adding to it
        ruleset = (
            f"destroy table inet {table_name}\n"
            f"table inet {table_name} {{\n"
            f"    chain forward {{\n"
            f"        type filter hook forward priority filter; policy accept;\n"
            f'        iifname "{ni.veth}" ip daddr {server_ip} accept\n'
            f"{extra_accept_rules}"
            f'        iifname "{ni.veth}" drop\n'
            f"    }}\n"
            f"}}\n"
        )

        process = await asyncio.create_subprocess_exec(
            "nft", "-f", "-",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await process.communicate(input=ruleset.encode())
        if process.returncode != 0:
            raise RuntimeError(
                f"Failed to install kill_switch nftables rules (exit code {process.returncode})"
            )
        logger.info("Kill switch activated for {} (allow {})", ni.veth, server_ip)

        try:
            yield
        finally:
            await run(["nft", "delete", "table", "inet", table_name])
            logger.info("Kill switch deactivated for {}", ni.veth)
