import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

from loguru import logger

from ._run import run
from .network_interfaces import NetworkInterfaces


class KillSwitch:

    @staticmethod
    @asynccontextmanager
    async def activate(
        ni: NetworkInterfaces,
        server_ip: str,
    ) -> AsyncIterator[None]:
        table_name = f"kill_switch_{ni.veth}"
        ruleset = (
            f"table inet {table_name} {{\n"
            f"    chain forward {{\n"
            f"        type filter hook forward priority filter; policy accept;\n"
            f'        iifname "{ni.veth}" ip daddr {server_ip} accept\n'
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
