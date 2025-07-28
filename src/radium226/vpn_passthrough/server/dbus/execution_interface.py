from loguru import logger

from sdbus import (
    dbus_method_async,
    dbus_property_async,
    DbusInterfaceCommonAsync,
    DbusUnprivilegedFlag,
)

from ..core import Execution




class ExecutionInterface(
    DbusInterfaceCommonAsync,
    interface_name="radium226.vpn_passthrough.Execution",
):
    
    _execution: Execution

    _exit_code: int | None = None
    _status: str = "running"


    def __init__(self, execution: Execution):
        super().__init__()
        self._execution = execution


    @dbus_property_async(
        property_signature='as',
        property_name="Command",
    )
    def command(self) -> list[str]:
        return self._execution.command

    @dbus_method_async(
        input_signature="i",
        method_name="SendSignal",
        flags=DbusUnprivilegedFlag,
    )
    async def send_signal(self, signal: int) -> None:
        await self._execution.send_signal(signal)


    @dbus_property_async(
        property_signature='s',
        property_name="Status",
    )
    def status(self) -> str:
        return self._status
    

    @status.setter_private
    def _set_status(self, status: str) -> None:
        logger.trace("_set_status({status})", status=status)
        self._status = status


    @dbus_property_async(
        property_signature='i',
        property_name="ExitCode",
    )
    def exit_code(self) -> int:
        return -1 if ( exit_code := self._exit_code ) is None else exit_code
    

    @exit_code.setter_private
    def _set_exit_code(self, exit_code: int) -> None:
        logger.debug("_set_exit_code({exit_code})", exit_code=exit_code)
        self._exit_code = exit_code