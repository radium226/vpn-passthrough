from typing import AsyncGenerator, Self
from contextlib import asynccontextmanager
from loguru import logger
from pathlib import Path


from ...shared.subprocess import run
from .network_interfaces import NetworkInterfaces



class Internet():

    def __init__(self) -> None:
        pass

    @classmethod
    @asynccontextmanager
    async def share(cls, name: str, server_ip: str, network_interfaces: NetworkInterfaces) -> AsyncGenerator[Self, None]:
        logger.debug("Sharing internet connection...")
        try:
            command=[
                "nft",
                "-f", str(Path(__file__).parent / "internet.nft"),
                "-D", f"name={name}",
                "-D", f"veth_name={network_interfaces.veth.name}",
                "-D", f"veth_addr={network_interfaces.veth.addr}",
                "-D", f"vpeer_name={network_interfaces.vpeer.name}",
                "-D", f"vpeer_addr={network_interfaces.vpeer.addr}",
                "-D", f"server_ip={server_ip}",
            ]
            await run(command, check=True)
            yield cls()
        finally:
            logger.debug("Unsharing internet sharing...")
            await run(["nft", "delete", "table", "inet", "vpt"], check=True)