import os
import subprocess

import pytest

from radium226.vpn_passthrough.server.dns_leak_guard import NETNS_TABLE_NAME, DNSLeakGuard
from radium226.vpn_passthrough.server.namespace import Namespace
from radium226.vpn_passthrough.server.network_interfaces import NetworkInterfaces

pytestmark = pytest.mark.skipif(
    os.geteuid() != 0,
    reason="creating nftables tables and network namespaces requires root",
)


async def _nft_list_in_namespace(namespace: Namespace, table_name: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["nft", "list", "table", "inet", table_name],
        capture_output=True,
        text=True,
        preexec_fn=namespace.enter,
    )


@pytest.mark.asyncio
async def test_dns_leak_guard_blocks_dns_on_both_sides(tmp_path):
    async with Namespace.create("dlg-test", base_folder_path=tmp_path) as namespace:
        async with NetworkInterfaces.add(namespace, cidr="10.233.0.0/24") as ni:
            host_table_name = f"dns_leak_guard_{ni.veth}"

            async with DNSLeakGuard.activate(namespace, ni):
                host_ruleset = subprocess.run(
                    ["nft", "list", "table", "inet", host_table_name],
                    capture_output=True, text=True, check=True,
                ).stdout
                assert f'iifname "{ni.veth}" tcp dport 53 drop' in host_ruleset
                assert f'iifname "{ni.veth}" udp dport 53 drop' in host_ruleset

                netns_result = await _nft_list_in_namespace(namespace, NETNS_TABLE_NAME)
                assert netns_result.returncode == 0
                assert f'oifname "{ni.vpeer}" tcp dport 53 drop' in netns_result.stdout
                assert f'oifname "{ni.vpeer}" udp dport 53 drop' in netns_result.stdout

            # both tables gone once the context manager exits
            assert subprocess.run(
                ["nft", "list", "table", "inet", host_table_name], capture_output=True
            ).returncode != 0
            assert (await _nft_list_in_namespace(namespace, NETNS_TABLE_NAME)).returncode != 0
