from loguru import logger

from ..server.dbus import ExecutionInterface
from ..shared.dbus import wait_for_property, to_be


class Execution():

    _interface: ExecutionInterface

    def __init__(self, interface: ExecutionInterface):
        self._interface = interface


    async def wait_for(self) -> int:
        logger.debug("Waiting for execution to finish...")
        await wait_for_property(self._interface.status, to_be("finished"))
        exit_code = await self._interface.exit_code.get_async()
        return exit_code
    
    async def send_signal(self, signal_value: int) -> None:
        await self._interface.send_signal(signal_value)

