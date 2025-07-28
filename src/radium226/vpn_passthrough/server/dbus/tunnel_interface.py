from contextlib import AsyncExitStack
from pathlib import Path
import asyncio

from sdbus import (
    dbus_method_async,
    DbusObjectManagerInterfaceAsync,
    dbus_property_async,
    DbusUnprivilegedFlag,
)

from loguru import logger

from ..core import Tunnel
from .execution_interface import ExecutionInterface




class TunnelInterface(
    DbusObjectManagerInterfaceAsync,
    interface_name="radium226.vpn_passthrough.Tunnel",
):
    _ip: str | None 
    _status: str

    _exit_stack: AsyncExitStack
    
    _tunnel: Tunnel | None = None

    def __init__(self, initial_status: str, initial_ip: str | None = None):
        super().__init__()
        self._status = initial_status
        self._ip = initial_ip

    @property
    def tunnel(self) -> Tunnel:
        if not self._tunnel:
            raise Exception("Tunnel is not yet opened!")
        
        return self._tunnel
    
    @tunnel.setter
    def tunnel(self, tunnel: Tunnel) -> None:
        logger.debug(f"Setting tunnel: {tunnel.name}")
        self._tunnel = tunnel

    @dbus_property_async(
        property_name="IP",
        property_signature="s",
    )
    def ip(self) -> str:
        return self._ip or ""

    @ip.setter_private
    def _set_ip(self, ip: str) -> None:
        logger.debug(f"Setting IP: {ip}")
        self._ip = ip


    @dbus_property_async(
        property_name="Status",
        property_signature="s",
    )
    def status(self) -> str:
        return self._status
    
    @status.setter_private
    def _set_status(self, status: str) -> None:
        self._status = status


    @dbus_method_async(
        method_name="Execute",
        input_signature="ashhhusa{ss}",
        input_args_names=["command", "stdin", "stdout", "stderr", "uid", "cwd", "env"],
        # input_signature="ashhha{ss}us",
        result_signature="o",
        result_args_names=["execution_path"],
        flags=DbusUnprivilegedFlag,
    )
    async def execute(
        self,
        command: list[str],
        stdin: int,
        stdout: int,
        stderr: int,
        uid: int,
        cwd: str,
        env: dict[str, str],
    ) -> str:
        assert self._tunnel is not None, "Tunnel must be set before executing commands"
        try:
            execution = await self.tunnel.execute(
                command,
                stdin=stdin,
                stdout=stdout,
                stderr=stderr,
                uid=uid,
                cwd=Path(cwd),
                env=env,
            )
            execution_interface = ExecutionInterface(execution)
            execution_path = f"/radium226/vpn_passthrough/TunnelManager/Tunnel/{self._tunnel.name}/Execution/{execution.name}"
            logger.debug(f"Exporting ExecutionInterface at path: {execution_path}")

            try:
                handle = self.export_with_manager(
                    execution_path,
                    execution_interface,
                )
                logger.debug(f"{handle=}")
            except Exception as e:
                logger.warning(f"Failed to export ExecutionInterface: {e}")
                await asyncio.sleep(60)

            async def wait_for_execution() -> None:
                try:
                    logger.debug("Waiting for execution to finish...")
                    exit_code = await execution.wait_for()
                    await execution_interface.exit_code.set_async(exit_code)
                    await execution_interface.status.set_async("finished")
                    logger.debug("Execution finished with exit code: {exit_code}", exit_code=exit_code)
                except Exception as e:
                    logger.error(f"Execution failed: {e}")
                    raise e
            
            asyncio.create_task(wait_for_execution())

            return execution_path
        except Exception as e:
            logger.error(f"Failed to execute command: {e}")
            raise e
            