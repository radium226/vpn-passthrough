from typing import Generator
from contextlib import contextmanager
from loguru import logger
from dataclasses import dataclass
from loguru import logger



@dataclass
class PortForwarding:


    @classmethod
    def start(cls) -> "PortForwarding":
        logger.debug(f"Starting port forwarding...")
        return cls()

    def stop(self) -> None:
        logger.debug(f"Stopping port forwarding...")


@contextmanager
def start_port_forwarding() -> Generator[PortForwarding, None, None]:
    port_forwarding = PortForwarding.start()
    try:
        yield port_forwarding
    finally:
        port_forwarding.stop()