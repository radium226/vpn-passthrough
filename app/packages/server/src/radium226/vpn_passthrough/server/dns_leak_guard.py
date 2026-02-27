import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

from loguru import logger

from ._run import run
from .netns import Namespace
from .network_interfaces import NetworkInterfaces


NETNS_TABLE_NAME = "dns_leak_guard"


class DnsLeakGuard:

    @staticmethod
    @asynccontextmanager
    async def activate(netns: Namespace, ni: NetworkInterfaces) -> AsyncIterator[None]:
        # Host-side table: block DNS forwarding from the veth interface.
        # This is reliable because it runs on the host with full CAP_NET_ADMIN.
        host_table_name = f"dns_leak_guard_{ni.veth}"
        host_ruleset = (
            f"table inet {host_table_name} {{\n"
            f"    chain forward {{\n"
            f"        type filter hook forward priority filter; policy accept;\n"
            f'        iifname "{ni.veth}" meta l4proto {{ tcp, udp }} th dport 53 drop\n'
            f"    }}\n"
            f"}}\n"
        )

        host_process = await asyncio.create_subprocess_exec(
            "nft", "-f", "-",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await host_process.communicate(input=host_ruleset.encode())
        if host_process.returncode != 0:
            raise RuntimeError(f"Failed to install host-side dns_leak_guard nftables rules (exit code {host_process.returncode})")

        # Netns-internal table: best-effort defense-in-depth.
        # May fail due to user namespace capability issues.
        netns_installed = False
        netns_ruleset = (
            f"table inet {NETNS_TABLE_NAME} {{\n"
            f"    chain output {{\n"
            f"        type filter hook output priority 0; policy accept;\n"
            f'        oifname "{ni.vpeer}" meta l4proto {{ tcp, udp }} th dport 53 drop\n'
            f"    }}\n"
            f"}}\n"
        )

        netns_process = await asyncio.create_subprocess_exec(
            "nft", "-f", "-",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            preexec_fn=netns.enter,
        )
        stdout, stderr = await netns_process.communicate(input=netns_ruleset.encode())
        if netns_process.returncode != 0:
            logger.warning(f"Failed to install netns-internal dns_leak_guard rules (exit code {netns_process.returncode}): {stderr.decode().strip()}")
        else:
            netns_installed = True

        try:
            yield
        finally:
            if netns_installed:
                await run(["nft", "delete", "table", "inet", NETNS_TABLE_NAME], preexec_fn=netns.enter)
            await run(["nft", "delete", "table", "inet", host_table_name])
