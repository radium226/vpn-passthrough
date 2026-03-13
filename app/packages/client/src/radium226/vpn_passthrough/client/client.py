import asyncio
import getpass
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Awaitable, Callable, Never

from loguru import logger

from radium226.vpn_passthrough.ipc import Client as IPCClient
from radium226.vpn_passthrough.ipc.protocol import ResponseHandler

from radium226.vpn_passthrough.messages import (
    CODEC,
    CommandNotFound,
    ConfigUsed,
    ConnectedToVPN,
    DNSConfigured,
    RegionsListed,
    Country,
    CreateTunnel,
    DestroyTunnel,
    KillProcess,
    ListRegions,
    ListTunnels,
    PortsRebound,
    ProcessKilled,
    ProcessRestarted,
    ProcessStarted,
    ProcessTerminated,
    RunProcess,
    StartTunnel,
    Tunnel,
    TunnelCreated,
    TunnelDestroyed,
    TunnelInfo,
    TunnelStarted,
    TunnelStatusUpdated,
    TunnelStopped,
    TunnelsListed,
)


class Client:
    def __init__(self, ipc: IPCClient) -> None:
        self.ipc = ipc
        self._tunnel_watch_tasks: dict[str, asyncio.Task[None]] = {}

    @classmethod
    @asynccontextmanager
    async def connect(cls, socket_file_path: Path) -> AsyncIterator["Client"]:
        logger.debug("Connecting to {}", socket_file_path)
        async with IPCClient.connect(socket_file_path, CODEC) as ipc:
            yield cls(ipc)

    async def run_process(
        self,
        command: str,
        args: list[str] | None = None,
        *,
        fds: list[int] | None = None,
        kill_with: int | None = None,
        in_tunnel: Tunnel | None = None,
        cwd: str | None = None,
        username: str | None = None,
        gid: int | None = None,
        on_pid_received: Callable[[int], Awaitable[None]] | None = None,
    ) -> int:
        loop = asyncio.get_running_loop()
        exit_code_future: asyncio.Future[int] = loop.create_future()

        async def on_event(event: ProcessStarted | ProcessRestarted, fds: list[int]) -> None:
            match event:
                case ProcessStarted(pid=pid):
                    logger.debug("Process started (pid={})", pid)
                    if on_pid_received is not None:
                        await on_pid_received(pid)
                case ProcessRestarted(pid=pid, forwarded_ports=forwarded_ports):
                    logger.debug("Process restarted (pid={}, forwarded_ports={})", pid, forwarded_ports)
                    if on_pid_received is not None:
                        await on_pid_received(pid)

        async def on_response(response: ProcessTerminated | CommandNotFound, fds: list[int]) -> None:
            match response:
                case ProcessTerminated(exit_code=exit_code):
                    exit_code_future.set_result(exit_code)
                case CommandNotFound():
                    exit_code_future.set_result(127)

        await self.ipc.request(
            RunProcess(
                id=str(uuid.uuid4()),
                command=command,
                args=args or [],
                kill_with=kill_with,
                in_tunnel=in_tunnel,
                cwd=cwd,
                username=username or getpass.getuser(),
                gid=gid,
                client_pid=os.getpid(),
                env=dict(os.environ),
            ),
            handler=ResponseHandler[ProcessStarted | ProcessRestarted, ProcessTerminated | CommandNotFound](
                on_event=on_event,
                on_response=on_response,
            ),
            fds=fds or [],
        )

        return await exit_code_future

    async def kill_process(self, pid: int, signal: int) -> None:
        loop = asyncio.get_running_loop()
        done: asyncio.Future[None] = loop.create_future()

        async def on_response(response: ProcessKilled, fds: list[int]) -> None:
            done.set_result(None)

        await self.ipc.request(
            KillProcess(id=str(uuid.uuid4()), pid=pid, signal=signal),
            handler=ResponseHandler[Never, ProcessKilled](on_response=on_response),
            fds=[],
        )

        await done

    async def create_tunnel(
        self,
        name: str,
        *,
        region_id: str | None = None,
        credentials: dict[str, str] | None = None,
        names_of_ports_to_forward: list[str] | None = None,
        backend: str | None = None,
        on_tunnel_info_changed: Callable[[TunnelInfo], None] | None = None,
    ) -> TunnelCreated:
        loop = asyncio.get_running_loop()
        result: asyncio.Future[TunnelCreated] = loop.create_future()

        async def on_event(event: ConnectedToVPN | DNSConfigured, fds: list[int]) -> None:
            match event:
                case DNSConfigured(nameservers=nameservers):
                    logger.info("DNS configured (nameservers={})", nameservers)
                case ConnectedToVPN(remote_ip=remote_ip, gateway_ip=gateway_ip, tun_ip=tun_ip, forwarded_ports=forwarded_ports):
                    logger.info("Connected to VPN (remote_ip={}, gateway={}, tun_ip={}, forwarded_ports={})", remote_ip, gateway_ip, tun_ip, forwarded_ports)

        async def on_response(response: TunnelCreated, fds: list[int]) -> None:
            logger.info("Tunnel {} created", response.name)
            result.set_result(response)

        await self.ipc.request(
            CreateTunnel(
                id=str(uuid.uuid4()),
                name=name,
                region_id=region_id,
                credentials=credentials,
                names_of_ports_to_forward=names_of_ports_to_forward or [],
                backend=backend,
            ),
            handler=ResponseHandler[ConnectedToVPN | DNSConfigured, TunnelCreated](
                on_event=on_event,
                on_response=on_response,
            ),
            fds=[],
        )

        return await result

    async def start_tunnel(
        self,
        name: str,
        *,
        region_id: str | None = None,
        credentials: dict[str, str] | None = None,
        names_of_ports_to_forward: list[str] | None = None,
        backend: str | None = None,
        rebind_ports_every: float | None = None,
        on_ready: Callable[[], None] | None = None,
        on_config_used: Callable[[ConfigUsed], None] | None = None,
        on_tunnel_status_updated: Callable[[TunnelInfo], None] | None = None,
        on_ports_rebound: Callable[[PortsRebound], None] | None = None,
    ) -> None:
        loop = asyncio.get_running_loop()
        done: asyncio.Future[None] = loop.create_future()

        async def on_event(event: ConfigUsed | TunnelStarted | ConnectedToVPN | DNSConfigured | TunnelStatusUpdated | PortsRebound, fds: list[int]) -> None:
            match event:
                case ConfigUsed():
                    if on_config_used is not None:
                        on_config_used(event)
                case TunnelStarted():
                    logger.info("Tunnel {} started", name)
                    if on_ready is not None:
                        on_ready()
                case TunnelStatusUpdated(info=info):
                    if on_tunnel_status_updated is not None:
                        on_tunnel_status_updated(info)
                case DNSConfigured(nameservers=nameservers):
                    logger.info("DNS configured (nameservers={})", nameservers)
                case ConnectedToVPN(remote_ip=remote_ip, gateway_ip=gateway_ip, tun_ip=tun_ip, forwarded_ports=forwarded_ports):
                    logger.info("Connected to VPN (remote_ip={}, gateway={}, tun_ip={}, forwarded_ports={})", remote_ip, gateway_ip, tun_ip, forwarded_ports)
                case PortsRebound(forwarded_ports=forwarded_ports):
                    logger.info("Ports rebound (forwarded_ports={})", forwarded_ports)
                    if on_ports_rebound is not None:
                        on_ports_rebound(event)

        async def on_response(response: TunnelStopped, fds: list[int]) -> None:
            logger.info("Tunnel {} stopped", response.name)
            done.set_result(None)

        await self.ipc.request(
            StartTunnel(
                id=str(uuid.uuid4()),
                name=name,
                region_id=region_id,
                credentials=credentials,
                names_of_ports_to_forward=names_of_ports_to_forward or [],
                backend=backend,
                rebind_ports_every=rebind_ports_every,
            ),
            handler=ResponseHandler[ConfigUsed | TunnelStarted | ConnectedToVPN | DNSConfigured | TunnelStatusUpdated | PortsRebound, TunnelStopped](
                on_event=on_event,
                on_response=on_response,
            ),
            fds=[],
        )

        await done

    async def list_regions(self, *, backend: str | None = None) -> list[Country]:
        loop = asyncio.get_running_loop()
        result: asyncio.Future[list[Country]] = loop.create_future()

        async def on_response(response: RegionsListed, fds: list[int]) -> None:
            result.set_result(response.countries)

        await self.ipc.request(
            ListRegions(id=str(uuid.uuid4()), backend=backend),
            handler=ResponseHandler[Never, RegionsListed](on_response=on_response),
            fds=[],
        )

        return await result

    async def list_tunnels(self) -> list[TunnelInfo]:
        loop = asyncio.get_running_loop()
        result: asyncio.Future[list[TunnelInfo]] = loop.create_future()

        async def on_response(response: TunnelsListed, fds: list[int]) -> None:
            result.set_result(response.tunnels)

        await self.ipc.request(
            ListTunnels(id=str(uuid.uuid4())),
            handler=ResponseHandler[Never, TunnelsListed](on_response=on_response),
            fds=[],
        )

        return await result

    async def destroy_tunnel(self, name: str) -> None:
        loop = asyncio.get_running_loop()
        done: asyncio.Future[None] = loop.create_future()

        async def on_response(response: TunnelDestroyed, fds: list[int]) -> None:
            done.set_result(None)

        await self.ipc.request(
            DestroyTunnel(id=str(uuid.uuid4()), name=name),
            handler=ResponseHandler[Never, TunnelDestroyed](on_response=on_response),
            fds=[],
        )

        await done

