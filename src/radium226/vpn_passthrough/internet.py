from contextlib import contextmanager
from loguru import logger
from typing import Generator
from subprocess import run
from pathlib import Path

from .network_interfaces import NetworkInterfaces
from .netns import NetNS


@contextmanager
def share_internet(name: str, network_interfaces: NetworkInterfaces) -> Generator[None, None, None]:
    """
    Context manager to share internet connection.
    This is a placeholder for the actual implementation.
    """
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
        ]
        run(command, check=True)
        yield
    finally:
        logger.debug("Stopping internet sharing...")
        run(["nft", "delete", "table", "inet", "vpt"], check=True)