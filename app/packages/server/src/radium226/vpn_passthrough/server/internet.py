import asyncio
import json
import re
import string
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from loguru import logger

from ._run import run
from .network_interfaces import NetworkInterfaces


_NFT_TEMPLATE = (Path(__file__).parent / "internet.nft").read_text()


def _nft_ident(name: str) -> str:
    """Sanitize a tunnel name for use as an nftables identifier.

    nftables identifiers only allow [a-zA-Z0-9_/.]. Dashes and other
    characters (common in UUIDs or user-supplied names) must be replaced.
    """
    return re.sub(r"[^a-zA-Z0-9_/.]", "_", name)


async def _list_forward_chains() -> list[tuple[str, str, str]]:
    """List all nftables forward chains with ``policy drop``.

    Returns a list of ``(family, table, chain)`` tuples for every chain that
    hooks into ``forward`` and has a ``drop`` policy — these are the chains
    that can block traffic from our network namespaces.
    """
    proc = await asyncio.create_subprocess_exec(
        "nft", "--json", "list", "chains",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        logger.error("nft list chains failed (exit {}): {}", proc.returncode, stderr.decode().strip())
        raise RuntimeError(f"nft list chains failed with exit code {proc.returncode}")
    try:
        items = json.loads(stdout).get("nftables", [])
    except (json.JSONDecodeError, TypeError):
        logger.error("nft returned unparseable output: {!r}", stdout)
        raise
    chains: list[tuple[str, str, str]] = []
    for item in items:
        chain = item.get("chain")
        if chain is None:
            continue
        if chain.get("hook") == "forward" and chain.get("policy") == "drop":
            chains.append((chain["family"], chain["table"], chain["name"]))
    return chains


async def _try_insert_host_forward_rule(family: str, table: str, chain: str, *rule_args: str) -> int | None:
    """Insert an accept rule into a host forward chain.

    Returns the rule handle so it can be deleted on cleanup, or None if the
    insert failed.
    """
    proc = await asyncio.create_subprocess_exec(
        "nft", "--echo", "--json",
        "insert", "rule", family, table, chain, *rule_args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    if proc.returncode != 0:
        return None
    try:
        for item in json.loads(stdout).get("nftables", []):
            if "rule" in item:
                return item["rule"]["handle"]
    except (json.JSONDecodeError, KeyError, TypeError):
        pass
    return None


class Internet:
    @staticmethod
    @asynccontextmanager
    async def share(name: str, network_interfaces: NetworkInterfaces) -> AsyncIterator[None]:
        await run(["sysctl", "-w", "net.ipv4.ip_forward=1"], check=True)

        nft_name = _nft_ident(name)
        subnet = network_interfaces.subnet
        nft_rules = string.Template(_NFT_TEMPLATE).substitute(name=nft_name, subnet=subnet)

        process = await asyncio.create_subprocess_exec(
            "nft", "-f", "-",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await process.communicate(nft_rules.encode())
        if process.returncode != 0:
            raise RuntimeError(f"nft failed with exit code {process.returncode}")

        # The host may have nftables forward chains with `policy drop` in
        # various tables (e.g. `inet filter`, `inet firewalld`, etc.). An
        # `accept` verdict in our own table does NOT prevent those chains from
        # still processing — and dropping — the packet. We must inject explicit
        # accept rules into every such chain and remove them on cleanup.
        veth = network_interfaces.veth
        forward_chains = await _list_forward_chains()
        inserted_rules: list[tuple[str, str, str, int]] = []
        for family, table, chain in forward_chains:
            for ifoption in ("iifname", "oifname"):
                handle = await _try_insert_host_forward_rule(family, table, chain, ifoption, veth, "accept")
                if handle is not None:
                    inserted_rules.append((family, table, chain, handle))

        try:
            yield
        finally:
            for family, table, chain, handle in inserted_rules:
                await run(["nft", "delete", "rule", family, table, chain, "handle", str(handle)])
            await run(["nft", "delete", "table", "inet", f"vpt_{nft_name}"])
