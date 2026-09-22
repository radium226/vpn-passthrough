import asyncio
import os
import subprocess

import pytest

from radium226.vpn_passthrough.server.namespace import Namespace
from radium226.vpn_passthrough.server.network_interfaces import NetworkInterfaces

pytestmark = pytest.mark.skipif(
    os.geteuid() != 0,
    reason="creating network namespaces and veth pairs requires root",
)


async def _ip_in_namespace(namespace: Namespace, *args: str) -> str:
    proc = await asyncio.create_subprocess_exec(
        "ip", *args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        preexec_fn=namespace.enter,
    )
    stdout, stderr = await proc.communicate()
    assert proc.returncode == 0, stderr.decode()
    return stdout.decode()


@pytest.mark.asyncio
async def test_add_veth_pair_configures_both_ends(tmp_path):
    async with Namespace.create("nns-test", base_folder_path=tmp_path) as namespace:
        async with NetworkInterfaces.add(
            namespace,
            cidr="10.231.0.0/24",
            extra_routes=["10.231.1.0/24"],
        ) as ni:
            host_addr = subprocess.run(
                ["ip", "addr", "show", ni.veth], capture_output=True, text=True, check=True
            ).stdout
            assert ni.veth_ip in host_addr

            peer_addr = await _ip_in_namespace(namespace, "addr", "show", ni.vpeer)
            assert ni.vpeer_ip in peer_addr

            routes = await _ip_in_namespace(namespace, "route", "show")
            assert f"default via {ni.veth_ip}" in routes
            assert "10.231.1.0/24" in routes

            lo = await _ip_in_namespace(namespace, "link", "show", "lo")
            assert "UP" in lo

        # after the context manager exits, the host-side veth (and its peer) are gone
        result = subprocess.run(["ip", "link", "show", ni.veth], capture_output=True)
        assert result.returncode != 0
