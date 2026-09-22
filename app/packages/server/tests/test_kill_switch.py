import os
import subprocess

import pytest

from radium226.vpn_passthrough.server.kill_switch import KillSwitch
from radium226.vpn_passthrough.server.namespace import Namespace
from radium226.vpn_passthrough.server.network_interfaces import NetworkInterfaces

pytestmark = pytest.mark.skipif(
    os.geteuid() != 0,
    reason="creating nftables tables and network namespaces requires root",
)


@pytest.mark.asyncio
async def test_kill_switch_blocks_everything_except_server_and_extra_routes(tmp_path):
    async with Namespace.create("ks-test", base_folder_path=tmp_path) as namespace:
        async with NetworkInterfaces.add(namespace, cidr="10.232.0.0/24") as ni:
            async with KillSwitch.activate(
                ni, server_ip="203.0.113.10", extra_routes=["10.99.0.0/24"]
            ):
                table_name = f"kill_switch_{ni.veth}"
                ruleset = subprocess.run(
                    ["nft", "list", "table", "inet", table_name],
                    capture_output=True,
                    text=True,
                    check=True,
                ).stdout

                assert f'iifname "{ni.veth}" ip daddr 203.0.113.10 accept' in ruleset
                assert f'iifname "{ni.veth}" ip daddr 10.99.0.0/24 accept' in ruleset
                assert f'iifname "{ni.veth}" drop' in ruleset

            # table is gone once the context manager exits
            result = subprocess.run(
                ["nft", "list", "table", "inet", table_name], capture_output=True
            )
            assert result.returncode != 0
