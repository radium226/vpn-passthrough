from pathlib import Path
from loguru import logger
import sys
import os

from ..server.dbus import TunnelInterface, ExecutionInterface

from .execution import Execution



class Tunnel():

    name: str

    def __init__(self, name: str, interface: TunnelInterface):
        self._interface = interface
        self.name = name

    async def execute(self, command: list[str] | tuple[str]) -> Execution:
        try:
            if isinstance(command, tuple):
                command = list(command)

            execution_path = await self._interface.execute(
                command=command,
                stdin=sys.stdin.fileno(),
                stdout=sys.stdout.fileno(),
                stderr=sys.stderr.fileno(),
                uid=os.getuid(),
                cwd=str(Path.cwd()),
                env=dict(os.environ),
            )

            logger.debug("execution_path: {execution_path}", execution_path=execution_path)
            execution_interface = ExecutionInterface.new_proxy(
                "radium226.vpn_passthrough",
                execution_path,
            )
            execution = Execution(execution_interface)
            return execution
        except Exception as e:
            logger.error(f"Failed to execute command: {e}")
            raise e


    