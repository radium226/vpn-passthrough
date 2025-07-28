from contextlib import AsyncExitStack
from types import TracebackType
from typing import Self
from loguru import logger
import os
from pathlib import Path
from dataclasses import dataclass
from httpx import AsyncClient, ConnectTimeout
import asyncio
from threading import Thread
from queue import Queue
import traceback

from asyncio.subprocess import create_subprocess_exec

from ...shared.pia import Region, PIA

from .execution import Execution
from .netns import NetNS




@dataclass
class TunnelInfo():

    ip: str
    city: str
    region: str


class Tunnel():

    _name: str
    _region: Region
    _netns: NetNS | None
    _http_client: AsyncClient
    _pia: PIA

    _exit_stack: AsyncExitStack

    def __init__(self, name: str, region: Region, netns: NetNS | None, http_client: AsyncClient, pia: PIA):
        self._name = name
        self._region = region
        self._netns = netns
        self._http_client = http_client
        self._pia = pia

        self._exit_stack = AsyncExitStack()


    async def __aenter__(self) -> Self:
        return self
    

    async def __aexit__(
        self, 
        type: type[BaseException] | None, 
        value: BaseException | None, 
        traceback: TracebackType | None,
    ) -> bool | None:
        await self._exit_stack.aclose()
        return False


    async def forward_port(self) -> int:
        try:
            queue = Queue() # type: ignore[var-annotated]
            

            async def _do_forward_port() -> None:
                try:
                    logger.debug("Requesting port! ")
                    port, payload_and_signature = await self._pia.request_port()
                    await self._pia.bind_port(payload_and_signature)

                    async def bind_port() -> None:
                        try:
                            while True:
                                await asyncio.sleep(60)
                                await self._pia.bind_port(payload_and_signature)
                        except Exception as e:
                            logger.error("Failed to bind port: {e}", e=e)
                            raise e
                    
                    port_binding_task = asyncio.create_task(bind_port())

                    async def cancel_port_binding() -> None:
                        port_binding_task.cancel()
                        try:
                            await port_binding_task
                        except asyncio.CancelledError:
                            logger.debug("Port binding task was cancelled.")

                    self._exit_stack.push_async_callback(cancel_port_binding)

                    logger.info("Port {port} has been forwarded", port=port)
                    queue.put(port)
                except Exception as e:
                    traceback.print_exc()
                    logger.error("Something happened e={e}", e=e)
                    raise e

            def _thread_target() -> None:
                logger.debug("Thread started! ")
                if self._netns is not None:
                    os.setns(os.open(f"/var/run/netns/{self._netns.name}", os.O_RDONLY), os.CLONE_NEWNET)
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(_do_forward_port())

            logger.debug("Creating thread...")
            thread = Thread(target=_thread_target)
            thread.start()
            logger.debug("Waiting for thread to finish...")
            await asyncio.get_event_loop().run_in_executor(None, thread.join)
            port = await asyncio.get_event_loop().run_in_executor(None, queue.get)
            assert isinstance(port, int), "Port must be an integer"
            return port
        except Exception as e:
            logger.error("An error occurred while forwarding port: {error}", error=e)
            raise e
    

    async def lookup_info(self) -> TunnelInfo:
        queue = Queue() # type: ignore[var-annotated]

        async def _do_lookup_info() -> None:
            async with AsyncClient() as http_client:
                max_number_of_tries = 10
                for i in range(max_number_of_tries):
                    try:
                        response = await http_client.get("https://ipinfo.io/json")
                        data = response.json()

                        queue.put(
                            TunnelInfo(
                                ip=data["ip"],
                                city=data["city"],
                                region=data["region"],
                            )
                        )
                    except ConnectTimeout as e:
                        if i < max_number_of_tries - 1:
                            if i > max_number_of_tries / 2:
                                logger.warning("Unable to lookup info... (e={e})", e=e)
                            await asyncio.sleep(5)
                            continue
                        else:
                            raise e

        def _thread_target() -> None:
            if self._netns is not None:
                os.setns(os.open(f"/var/run/netns/{self._netns.name}", os.O_RDONLY), os.CLONE_NEWNET)
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            info = loop.run_until_complete(_do_lookup_info())
            queue.put(info)

        thread = Thread(target=_thread_target)
        thread.start()
        await asyncio.get_event_loop().run_in_executor(None, thread.join)
        info = await asyncio.get_event_loop().run_in_executor(None, queue.get)
        assert isinstance(info, TunnelInfo), "Info must be an instance of TunnelInfo"
        return info

    
    async def execute(self, command: list[str], stdin: int, stdout: int, stderr: int, uid: int, cwd: Path, env: dict[str, str]) -> Execution:
        
        def preexec_fn() -> None:
            if netns := self._netns:
                try:
                    logger.debug("Setting NetNS for command execution to: {netns_name}", netns_name=netns.name)
                    fd = os.open(f"/var/run/netns/{netns.name}", os.O_RDONLY)
                    logger.debug(f"Opened NetNS file descriptor: {fd}")

                    os.setns(fd, os.CLONE_NEWNET)
                except Exception as e:
                    logger.error(f"Failed to set NetNS: {e}")
                    raise

            try:
                logger.debug("Setting UID for command execution to: {uid}", uid=uid)
                os.setuid(uid)
            except Exception as e:
                logger.error(f"Failed to set UID: {e}")
                raise


        process = await create_subprocess_exec(
            *command,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            preexec_fn=preexec_fn,
            cwd=str(cwd),
            env=env,
        )
        logger.debug("Process created with PID: {pid}", pid=process.pid)

        execution = Execution(
            process=process, 
            command=command,
        )
        
        return execution


    @property
    def name(self) -> str:
        return self._name
    
    @property
    def region(self) -> Region:
        return self._region