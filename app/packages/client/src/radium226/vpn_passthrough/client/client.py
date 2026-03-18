import asyncio
import getpass
import os
import random
import uuid
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Awaitable, Callable, Never, overload

from .config import ClientConfig, TunnelConfig

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
    TunnelCreated,
    TunnelDestroyed,
    TunnelInfo,
    TunnelStarted,
    TunnelStatusUpdated,
    TunnelStopped,
    TunnelsListed,
)


class Client:
    ipc: IPCClient
    _tunnel_watch_tasks: dict[str, asyncio.Task[None]]
    def __init__(self, ipc: IPCClient) -> None:
        self.ipc = ipc
        self._tunnel_watch_tasks: dict[str, asyncio.Task[None]] = {}

    @staticmethod
    @asynccontextmanager
    async def _connect(socket_file_path: Path) -> AsyncIterator["Client"]:
        async with IPCClient.connect(socket_file_path, CODEC) as ipc:
            yield Client(ipc)

    @overload
    @classmethod
    def connect(cls, config: ClientConfig) -> AbstractAsyncContextManager["Client"]: ...

    @overload
    @classmethod
    def connect(cls, socket_file_path: Path) -> AbstractAsyncContextManager["Client"]: ...

    @classmethod
    def connect(cls, config: ClientConfig | Path) -> AbstractAsyncContextManager["Client"]:
        if isinstance(config, Path):
            config = ClientConfig(socket_file_path=config)
        return cls._connect(config.socket_file_path)

    async def run_process(
        self,
        command: str,
        args: list[str] | None = None,
        *,
        fds: list[int] | None = None,
        kill_with: int | None = None,
        tunnel_name: str | None = None,
        cwd: str | None = None,
        username: str | None = None,
        gid: int | None = None,
        on_pid_received: Callable[[int], Awaitable[None]] | None = None,
        configure_with: str | None = None,
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
                tunnel_name=tunnel_name,
                cwd=cwd,
                username=username or getpass.getuser(),
                gid=gid,
                client_pid=os.getpid(),
                env=dict(os.environ),
                configure_with=configure_with,
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

    @overload
    async def create_tunnel(self, config: TunnelConfig) -> TunnelCreated: ...

    @overload
    async def create_tunnel(
        self,
        name: str,
        *,
        region_id: str | None = None,
        names_of_ports_to_forward: list[str] | None = None,
        backend_name: str | None = None,
        veth_cidr: str | None = None,
        ports_to_forward_from_vpeer_to_loopback: list[int] | None = None,
    ) -> TunnelCreated: ...

    async def create_tunnel(
        self,
        name_or_config: str | TunnelConfig,
        *,
        region_id: str | None = None,
        names_of_ports_to_forward: list[str] | None = None,
        backend_name: str | None = None,
        veth_cidr: str | None = None,
        ports_to_forward_from_vpeer_to_loopback: list[int] | None = None,
    ) -> TunnelCreated:
        if isinstance(name_or_config, TunnelConfig):
            config = name_or_config
            name = config.name
            region_id = config.region_id
            names_of_ports_to_forward = config.names_of_ports_to_forward
            backend_name = config.backend_name
            veth_cidr = config.veth_cidr
            ports_to_forward_from_vpeer_to_loopback = config.ports_to_forward_from_vpeer_to_loopback
        else:
            name = name_or_config

        if region_id is None:
            countries = await self.list_regions(backend_name=backend_name)
            if names_of_ports_to_forward:
                countries = [country for country in countries if country.port_forward]
            region_id = random.choice(countries).region_id

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
                names_of_ports_to_forward=names_of_ports_to_forward or [],
                backend_name=backend_name,
                veth_cidr=veth_cidr,
                ports_to_forward_from_vpeer_to_loopback=ports_to_forward_from_vpeer_to_loopback or [],
            ),
            handler=ResponseHandler[ConnectedToVPN | DNSConfigured, TunnelCreated](
                on_event=on_event,
                on_response=on_response,
            ),
            fds=[],
        )

        return await result

    @overload
    async def start_tunnel(self, config: TunnelConfig, *, on_ready: Callable[[], None] | None = None, on_config_used: Callable[[ConfigUsed], None] | None = None, on_tunnel_status_updated: Callable[[TunnelInfo], None] | None = None, on_ports_rebound: Callable[[PortsRebound], None] | None = None) -> None: ...

    @overload
    async def start_tunnel(
        self,
        name: str,
        *,
        region_id: str | None = None,
        names_of_ports_to_forward: list[str] | None = None,
        backend_name: str | None = None,
        rebind_ports_every: float | None = None,
        veth_cidr: str | None = None,
        ports_to_forward_from_vpeer_to_loopback: list[int] | None = None,
        on_ready: Callable[[], None] | None = None,
        on_config_used: Callable[[ConfigUsed], None] | None = None,
        on_tunnel_status_updated: Callable[[TunnelInfo], None] | None = None,
        on_ports_rebound: Callable[[PortsRebound], None] | None = None,
    ) -> None: ...

    async def start_tunnel(
        self,
        name_or_config: str | TunnelConfig,
        *,
        region_id: str | None = None,
        names_of_ports_to_forward: list[str] | None = None,
        backend_name: str | None = None,
        rebind_ports_every: float | None = None,
        veth_cidr: str | None = None,
        ports_to_forward_from_vpeer_to_loopback: list[int] | None = None,
        on_ready: Callable[[], None] | None = None,
        on_config_used: Callable[[ConfigUsed], None] | None = None,
        on_tunnel_status_updated: Callable[[TunnelInfo], None] | None = None,
        on_ports_rebound: Callable[[PortsRebound], None] | None = None,
    ) -> None:
        if isinstance(name_or_config, TunnelConfig):
            config = name_or_config
            name = config.name
            region_id = config.region_id
            names_of_ports_to_forward = config.names_of_ports_to_forward
            backend_name = config.backend_name
            veth_cidr = config.veth_cidr
            rebind_ports_every = config.rebind_ports_every
            ports_to_forward_from_vpeer_to_loopback = config.ports_to_forward_from_vpeer_to_loopback
        else:
            name = name_or_config

        if region_id is None:
            countries = await self.list_regions(backend_name=backend_name)
            if names_of_ports_to_forward:
                countries = [country for country in countries if country.port_forward]
            region_id = random.choice(countries).region_id
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
                names_of_ports_to_forward=names_of_ports_to_forward or [],
                backend_name=backend_name,
                rebind_ports_every=rebind_ports_every,
                veth_cidr=veth_cidr,
                ports_to_forward_from_vpeer_to_loopback=ports_to_forward_from_vpeer_to_loopback or [],
            ),
            handler=ResponseHandler[ConfigUsed | TunnelStarted | ConnectedToVPN | DNSConfigured | TunnelStatusUpdated | PortsRebound, TunnelStopped](
                on_event=on_event,
                on_response=on_response,
            ),
            fds=[],
        )

        await done

    async def list_regions(self, *, backend_name: str | None = None) -> list[Country]:
        loop = asyncio.get_running_loop()
        result: asyncio.Future[list[Country]] = loop.create_future()

        async def on_response(response: RegionsListed, fds: list[int]) -> None:
            result.set_result(response.countries)

        await self.ipc.request(
            ListRegions(id=str(uuid.uuid4()), backend_name=backend_name),
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

    async def lookup_tunnel(self, name: str) -> TunnelInfo:
        tunnels = await self.list_tunnels()
        info = next((tunnel for tunnel in tunnels if tunnel.name == name), None)
        if info is None:
            raise KeyError(f"Tunnel {name!r} not found")
        return info

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

