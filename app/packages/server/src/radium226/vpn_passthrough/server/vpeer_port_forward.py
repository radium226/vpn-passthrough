import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

from ._run import run
from .namespace import Namespace
from .network_interfaces import NetworkInterfaces


class VpeerPortForward:

    @staticmethod
    @asynccontextmanager
    async def setup(namespace: Namespace, ni: NetworkInterfaces, ports: list[int]) -> AsyncIterator[None]:
        if not ports:
            yield
            return

        port_set = "{ " + ", ".join(str(p) for p in ports) + " }"

        await run(
            ["sysctl", "-w", f"net.ipv4.conf.{ni.vpeer}.route_localnet=1"],
            preexec_fn=namespace.enter,
        )

        ruleset = (
            "table ip vpeer_port_forward {\n"
            "    chain prerouting {\n"
            "        type nat hook prerouting priority dstnat; policy accept;\n"
            f'        iifname "{ni.vpeer}" tcp dport {port_set} dnat to 127.0.0.1\n'
            f'        iifname "{ni.vpeer}" udp dport {port_set} dnat to 127.0.0.1\n'
            "    }\n"
            "}\n"
        )

        process = await asyncio.create_subprocess_exec(
            "nft", "-f", "-",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            preexec_fn=namespace.enter,
        )
        stdout, stderr = await process.communicate(input=ruleset.encode())
        if process.returncode != 0:
            raise RuntimeError(f"Failed to install vpeer_port_forward nftables rules: {stderr.decode().strip()}")

        try:
            yield
        finally:
            await run(["nft", "delete", "table", "ip", "vpeer_port_forward"], preexec_fn=namespace.enter)
            await run(
                ["sysctl", "-w", f"net.ipv4.conf.{ni.vpeer}.route_localnet=0"],
                preexec_fn=namespace.enter,
            )
