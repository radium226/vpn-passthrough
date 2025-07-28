from typing import Self, AsyncGenerator
from contextlib import asynccontextmanager
from loguru import logger
import os
import asyncio
import jc
from dataclasses import dataclass

from ...shared.subprocess import run



@dataclass
class PingResult():
    
    packet_loss_ratio: float




class NetNS():

    _name: str

    def __init__(self, name: str):
        self._name = name

    @property
    def name(self) -> str:
        return self._name
    

    @classmethod
    @asynccontextmanager
    async def create(cls, name: str) -> AsyncGenerator[Self, None]:
        logger.debug(f"Creating NetNS with name: {name}")
        await run(["ip", "netns", "add", name])
        
        try:
            yield cls(
                name=name,
            )
        finally:
            logger.debug(f"Deleting NetNS with name: {name}")
            await run(["ip", "netns", "delete", name])

    def _set_netns(self) -> None:
        logger.debug(f"Setting NetNS to: {self._name}")
        fd = os.open(f"/var/run/netns/{self._name}", os.O_RDONLY)
        logger.debug(f"Opened NetNS file descriptor: {fd}")
        os.setns(fd, os.CLONE_NEWNET)

    def enter(self) -> None:
        logger.debug(f"Switching to NetNS: {self._name}")
        self._set_netns()


    async def run(self, command: list[str]) -> int:
        logger.debug(f"Running command in NetNS '{self._name}': {' '.join(command)}")
        
        exit_code = await run(
            command,
            preexec_fn=self._set_netns,
        )
        return exit_code

    async def ping(self, ip_addr: str, count: int=5, timeout: float=0.5) -> PingResult:
        process = await asyncio.create_subprocess_exec(
            "ping",
            "-qc", str(count),
            "-i", str(timeout),
            str(ip_addr),
            preexec_fn=self._set_netns,
            stdout=asyncio.subprocess.PIPE,
        )

        stdout, _ = await process.communicate()
        result = jc.parse(
            "ping",
            stdout.decode(),
        )

        assert isinstance(result, dict), "Expected jc to return a dictionary"
        return PingResult(
            packet_loss_ratio=result.get("packet_loss_percent", "100.00") / 100.00,
        )