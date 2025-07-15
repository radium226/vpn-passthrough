from typing import Generator
from contextlib import contextmanager
from loguru import logger
from dataclasses import dataclass
from subprocess import run

from pathlib import Path



@contextmanager
def create_netns(name: str) -> Generator["NetNS", None, None]:
    
    netns = NetNS.create(name)
    try:
        yield netns
    finally:
        netns.destroy()



@dataclass
class NetNS:
    
    name: str


    @classmethod
    def create(cls, name: str) -> "NetNS":
        logger.debug(f"Creating NetNS with name: {name}")
        command = ["ip", "netns", "add", str(name)]
        run(command, check=True)
        return cls(name=name)


    def destroy(self) -> None:
        logger.debug(f"Destroying NetNS with name: {self.name}")
        command = ["ip", "netns", "delete", str(self.name)]
        run(command, check=True)        

    def exec(self, command: list[str]) -> None:
        logger.debug(f"Executing command in NetNS {self.name}: {command}")
        # Here you would implement the logic to execute the command in the network namespace
        run(["ip", "netns", "exec", self.name] + command, check=True)