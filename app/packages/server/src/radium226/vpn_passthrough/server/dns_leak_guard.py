import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

from loguru import logger

from radium226.vpn_passthrough.nftables_native import nftables_native

from .namespace import Namespace
from .network_interfaces import NetworkInterfaces


NETNS_TABLE_NAME = "dns_leak_guard"


class DNSLeakGuard:

    @staticmethod
    @asynccontextmanager
    async def activate(namespace: Namespace, ni: NetworkInterfaces) -> AsyncIterator[None]:
        # Host-side table: block DNS forwarding from the veth interface.
        # This is reliable because it runs on the host with full CAP_NET_ADMIN.
        host_table_name = f"dns_leak_guard_{ni.veth}"
        try:
            await asyncio.to_thread(
                nftables_native.install_dns_leak_guard_host, host_table_name, ni.veth
            )
        except OSError as e:
            raise RuntimeError(f"Failed to install host-side dns_leak_guard nftables rules: {e}") from e

        # Netns-internal table: best-effort defense-in-depth.
        # May fail due to user namespace capability issues.
        netns_installed = False
        try:
            await asyncio.to_thread(
                nftables_native.install_dns_leak_guard_netns,
                NETNS_TABLE_NAME, ni.vpeer, namespace.pid,
            )
            netns_installed = True
        except OSError as e:
            logger.warning(f"Failed to install namespace-internal dns_leak_guard rules: {e}")

        try:
            yield
        finally:
            if netns_installed:
                await asyncio.to_thread(
                    nftables_native.delete_table_in_netns, NETNS_TABLE_NAME, namespace.pid
                )
            await asyncio.to_thread(nftables_native.delete_table, host_table_name)
