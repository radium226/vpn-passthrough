import asyncio
import os
import signal
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from typing import Never

from jinja2 import Template, TemplateError

from loguru import logger

from radium226.vpn_passthrough.ipc.protocol import Emit

from radium226.vpn_passthrough.messages import (
    CommandNotFound,
    ConnectedToVPN,
    DNSConfigured,
    RegionsListed,
    Country,
    CreateTunnel,
    DestroyTunnel,
    KillProcess,
    ListRegions,
    ListTunnels,
    ProcessInfo,
    ProcessKilled,
    ProcessRestarted,
    ProcessStarted,
    ProcessTerminated,
    RunProcess,
    StartTunnel,
    TunnelCreated,
    TunnelDestroyed,
    TunnelInfo,
    TunnelName,
    TunnelStarted,
    TunnelStatusUpdated,
    TunnelStopped,
    TunnelsListed,
)
from radium226.vpn_passthrough.vpn import get_backend
from .dns import DNS
from .dns_leak_guard import DnsLeakGuard
from .internet import Internet
from .netns import Namespace
from .network_interfaces import NetworkInterfaces
from .linux import make_preexec_fn

_MIN_RESTART_INTERVAL = 1.0  # seconds — prevent tight restart loops


@dataclass
class _TunnelContext:
    public_ip: str
    gateway_ip: str
    tun_ip: str
    forwarded_ports: list[int]
    region_id: str | None = None
    forward_port: Callable[[], AbstractAsyncContextManager[int]] | None = None


class Service():

    def __init__(
        self,
        namespace_base_folder_path: Path,
        *,
        on_tunnels_changed: Callable[[list[TunnelInfo]], None] | None = None,
    ) -> None:
        self.namespace_base_folder_path = namespace_base_folder_path
        self.exit_stacks: dict[TunnelName, AsyncExitStack] = {}
        self.namespaces: dict[TunnelName, Namespace] = {}
        self.tunnel_contexts: dict[TunnelName, _TunnelContext] = {}
        self.processes: dict[TunnelName, dict[int, ProcessInfo]] = {}
        self._on_tunnels_changed = on_tunnels_changed
        self._tunnel_stop_signals: dict[TunnelName, asyncio.Future[None]] = {}
        self._tunnel_emit_fns: dict[TunnelName, Any] = {}  # Emit[TunnelStatusUpdated]

    @classmethod
    @asynccontextmanager
    async def create(
        cls,
        *,
        namespace_base_folder_path: Path,
        on_tunnels_changed: Callable[[list[TunnelInfo]], None] | None = None,
    ) -> AsyncIterator["Service"]:
        yield Service(namespace_base_folder_path, on_tunnels_changed=on_tunnels_changed)

    def _current_tunnels(self) -> list[TunnelInfo]:
        tunnels = []
        for name in self.namespaces:
            ctx = self.tunnel_contexts.get(name)
            procs = list(self.processes.get(name, {}).values())
            tunnels.append(TunnelInfo(
                name=name,
                vpn_connected=ctx is not None,
                region_id=ctx.region_id if ctx is not None else None,
                public_ip=ctx.public_ip if ctx is not None else None,
                gateway_ip=ctx.gateway_ip if ctx is not None else None,
                tun_ip=ctx.tun_ip if ctx is not None else None,
                forwarded_ports=ctx.forwarded_ports if ctx is not None else [],
                processes=procs,
            ))
        return tunnels

    async def _notify_tunnel_updated(self, tunnel_name: TunnelName) -> None:
        if self._on_tunnels_changed is not None:
            self._on_tunnels_changed(self._current_tunnels())
        emit_fn = self._tunnel_emit_fns.get(tunnel_name)
        if emit_fn is not None:
            info = next((t for t in self._current_tunnels() if t.name == tunnel_name), None)
            if info is not None:
                await emit_fn(TunnelStatusUpdated(info=info), [])

    async def _setup_tunnel(
        self,
        name: TunnelName,
        region_id: str | None,
        credentials: dict[str, str] | None,
        number_of_ports_to_forward: int,
        emit: Any,
        backend: str | None = None,
    ) -> None:
        stack = AsyncExitStack()
        try:
            netns = await stack.enter_async_context(Namespace.create(name, base_folder_path=self.namespace_base_folder_path))
            ni = await stack.enter_async_context(NetworkInterfaces.add(netns))
            await stack.enter_async_context(Internet.share(name, ni))

            if region_id is not None and credentials is not None:
                backend_instance = get_backend(backend or "pia")
                session = await stack.enter_async_context(
                    backend_instance.connect(
                        name,
                        enter_netns=netns.enter,
                        credentials=credentials,
                        region_id=region_id,
                        forwarded_port_count=number_of_ports_to_forward,
                    )
                )
                nameservers = list(session.dns_servers)
                logger.info("DNS configured in tunnel {} (nameservers={})", name, nameservers)
                await emit(DNSConfigured(nameservers=nameservers), [])
                await stack.enter_async_context(DNS.setup(netns, nameservers=nameservers))
                await stack.enter_async_context(DnsLeakGuard.activate(netns, ni))
                forwarded_ports = list(session.forwarded_ports)
                remote_ip = await self._fetch_remote_ip(netns)
                logger.info("Connected to VPN in tunnel {} (gateway={}, remote_ip={})", name, session.gateway_ip, remote_ip)
                await emit(ConnectedToVPN(remote_ip=remote_ip, gateway_ip=session.gateway_ip, tun_ip=session.tun_ip, forwarded_ports=forwarded_ports), [])
                self.tunnel_contexts[name] = _TunnelContext(
                    public_ip=remote_ip,
                    gateway_ip=session.gateway_ip,
                    tun_ip=session.tun_ip,
                    forwarded_ports=forwarded_ports,
                    region_id=region_id,
                    forward_port=session.forward_port,
                )
            else:
                await stack.enter_async_context(DNS.setup(netns, nameservers=None))

            self.namespaces[name] = netns
            self.exit_stacks[name] = stack
        except BaseException:
            self.tunnel_contexts.pop(name, None)
            await stack.aclose()
            raise


    async def handle_run_process(
        self,
        request: RunProcess,
        fds: list[int],
        emit: Emit[ProcessStarted | ProcessRestarted],
    ) -> tuple[ProcessTerminated | CommandNotFound, list[int]]:
        if len(fds) < 3:
            raise ValueError(f"Expected 3 file descriptors (stdin, stdout, stderr), got {len(fds)}")

        stdin_fd, stdout_fd, stderr_fd = fds[0], fds[1], fds[2]
        kill_signal = request.kill_with or signal.SIGTERM
        restart_every = (
            max(request.restart_every, _MIN_RESTART_INTERVAL)
            if request.restart_every is not None
            else None
        )
        port_rebind_every = (
            max(request.port_rebind_every, _MIN_RESTART_INTERVAL)
            if request.port_rebind_every is not None
            else None
        )

        if request.in_tunnel is None:
            raise ValueError("RunProcess requires in_tunnel")
        if request.username is None:
            raise ValueError("RunProcess requires username")

        tunnel_name_for_setup = request.in_tunnel.name
        if tunnel_name_for_setup not in self.namespaces:
            logger.info("Lazily creating tunnel {} for process", tunnel_name_for_setup)
            await self._setup_tunnel(tunnel_name_for_setup, None, None, 0, emit)

        namespace = self.namespaces[request.in_tunnel.name]
        tunnel_ctx_for_rebind = self.tunnel_contexts.get(request.in_tunnel.name) if port_rebind_every is not None else None

        preexec_fn = make_preexec_fn(
            request.username,
            namespace.pid,
            cwd=request.cwd,
        )

        first = True
        next_forwarded_ports: list[int] | None = None
        tunnel_name = request.in_tunnel.name
        self.processes.setdefault(tunnel_name, {})

        while True:
            ctx = self.tunnel_contexts.get(tunnel_name)
            jinja_vars = {
                "public_ip": ctx.public_ip if ctx is not None else "",
                "gateway_ip": ctx.gateway_ip if ctx is not None else "",
                "tun_ip": ctx.tun_ip if ctx is not None else "",
                "forwarded_ports": ctx.forwarded_ports if ctx is not None else [],
            }
            try:
                command = Template(request.command).render(**jinja_vars)
                args = [Template(arg).render(**jinja_vars) for arg in request.args]
            except TemplateError as e:
                logger.error("Jinja2 template error in command: {}", e)
                for fd in (stdin_fd, stdout_fd, stderr_fd):
                    try:
                        os.close(fd)
                    except OSError as close_err:
                        logger.warning("Failed to close fd {}: {}", fd, close_err)
                return CommandNotFound(request_id=request.id, command=request.command), []

            try:
                process = await asyncio.create_subprocess_exec(
                    command, *args,
                    stdin=stdin_fd,
                    stdout=stdout_fd,
                    stderr=stderr_fd,
                    start_new_session=True,
                    preexec_fn=preexec_fn,
                    env=request.env,
                )
            except FileNotFoundError:
                for fd in (stdin_fd, stdout_fd, stderr_fd):
                    try:
                        os.close(fd)
                    except OSError as e:
                        logger.warning("Failed to close fd {}: {}", fd, e)
                return CommandNotFound(request_id=request.id, command=command), []

            self.processes[tunnel_name][process.pid] = ProcessInfo(pid=process.pid, command=command, args=args)
            await self._notify_tunnel_updated(tunnel_name)

            if first:
                await emit(ProcessStarted(pid=process.pid), [])
                first = False
            else:
                ports = next_forwarded_ports if next_forwarded_ports is not None else (ctx.forwarded_ports if ctx is not None else [])
                logger.debug("Process restarted with pid {} (forwarded_ports={})", process.pid, ports)
                await emit(ProcessRestarted(pid=process.pid, forwarded_ports=ports), [])
                next_forwarded_ports = None

            timer_tasks: dict[str, asyncio.Task[None]] = {}
            if restart_every is not None:
                timer_tasks["restart"] = asyncio.create_task(asyncio.sleep(restart_every))
            if port_rebind_every is not None and tunnel_ctx_for_rebind is not None and tunnel_ctx_for_rebind.forward_port is not None:
                timer_tasks["rebind"] = asyncio.create_task(asyncio.sleep(port_rebind_every))

            if timer_tasks:
                wait_task = asyncio.create_task(process.wait())
                done, pending = await asyncio.wait(
                    [wait_task, *timer_tasks.values()],
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in pending:
                    task.cancel()

                rebind_timer = timer_tasks.get("rebind")
                restart_timer = timer_tasks.get("restart")

                if rebind_timer is not None and rebind_timer in done:
                    if tunnel_ctx_for_rebind is None or tunnel_ctx_for_rebind.forward_port is None:
                        raise RuntimeError("rebind timer fired but no forward_port available")
                    new_port_number = await self.exit_stacks[tunnel_name].enter_async_context(
                        tunnel_ctx_for_rebind.forward_port()
                    )
                    next_forwarded_ports = [new_port_number]
                    if ctx is not None:
                        self.tunnel_contexts[tunnel_name] = _TunnelContext(
                            public_ip=ctx.public_ip,
                            gateway_ip=ctx.gateway_ip,
                            tun_ip=ctx.tun_ip,
                            forwarded_ports=next_forwarded_ports,
                            region_id=ctx.region_id,
                        )
                    self.processes[tunnel_name].pop(process.pid, None)
                    await self._notify_tunnel_updated(tunnel_name)
                    os.killpg(os.getpgid(process.pid), kill_signal)
                    await process.wait()
                    continue
                elif restart_timer is not None and restart_timer in done:
                    self.processes[tunnel_name].pop(process.pid, None)
                    await self._notify_tunnel_updated(tunnel_name)
                    os.killpg(os.getpgid(process.pid), kill_signal)
                    await process.wait()
                    continue
                else:
                    break
            else:
                await process.wait()
                break

        self.processes[tunnel_name].pop(process.pid, None)
        await self._notify_tunnel_updated(tunnel_name)
        for fd in (stdin_fd, stdout_fd, stderr_fd):
            try:
                os.close(fd)
            except OSError as e:
                logger.warning("Failed to close fd {}: {}", fd, e)

        logger.debug("Process {} terminated with exit code {}", process.pid, process.returncode)
        return ProcessTerminated(request_id=request.id, exit_code=process.returncode or 0), []


    @staticmethod
    async def handle_kill_process(
        request: KillProcess,
        fds: list[int],
        emit: Emit[Never],
    ) -> tuple[ProcessKilled, list[int]]:
        logger.info("Killing process group {} with signal {}", request.pid, signal.Signals(request.signal).name)
        os.killpg(os.getpgid(request.pid), request.signal)
        return ProcessKilled(request_id=request.id, pid=request.pid), []


    @staticmethod
    async def _fetch_remote_ip(netns: Namespace) -> str:
        process = await asyncio.create_subprocess_exec(
            "curl", "ifconfig.me",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            preexec_fn=netns.enter,
        )
        stdout, stderr = await process.communicate()

        for line in stderr.decode().splitlines():
            logger.warning("Error fetching remote IP: {}", line)

        remote_ip = stdout.decode().strip()
        if remote_ip:
            return remote_ip
        else:
            raise RuntimeError("Could not determine remote IP from Cloudflare trace")

    async def handle_create_tunnel(
        self,
        request: CreateTunnel,
        fds: list[int],
        emit: Emit[ConnectedToVPN | DNSConfigured],
    ) -> tuple[TunnelCreated, list[int]]:
        await self._setup_tunnel(request.name, request.region_id, request.credentials, request.number_of_ports_to_forward, emit, backend=request.backend)
        logger.info("Tunnel {} created", request.name)
        if self._on_tunnels_changed is not None:
            self._on_tunnels_changed(self._current_tunnels())
        return TunnelCreated(request_id=request.id, name=request.name), []

    async def handle_start_tunnel(
        self,
        request: StartTunnel,
        fds: list[int],
        emit: Emit[TunnelStarted | ConnectedToVPN | DNSConfigured | TunnelStatusUpdated],
    ) -> tuple[TunnelStopped, list[int]]:
        await self._setup_tunnel(request.name, request.region_id, request.credentials, request.number_of_ports_to_forward, emit, backend=request.backend)
        logger.info("Tunnel {} started", request.name)
        if self._on_tunnels_changed is not None:
            self._on_tunnels_changed(self._current_tunnels())
        await emit(TunnelStarted(name=request.name), [])

        self._tunnel_emit_fns[request.name] = emit
        loop = asyncio.get_running_loop()
        stop: asyncio.Future[None] = loop.create_future()
        self._tunnel_stop_signals[request.name] = stop
        try:
            await stop
        finally:
            self._tunnel_emit_fns.pop(request.name, None)
            self._tunnel_stop_signals.pop(request.name, None)
        return TunnelStopped(request_id=request.id, name=request.name), []

    async def handle_destroy_tunnel(
        self,
        request: DestroyTunnel,
        fds: list[int],
        emit: Emit[Never],
    ) -> tuple[TunnelDestroyed, list[int]]:
        self.namespaces.pop(request.name, None)
        self.tunnel_contexts.pop(request.name, None)
        self.processes.pop(request.name, None)

        # Unblock handle_start_tunnel (and thus the client) before the slow
        # stack teardown so the client sees the stop immediately.
        stop = self._tunnel_stop_signals.get(request.name)
        if stop is not None and not stop.done():
            stop.set_result(None)

        stack = self.exit_stacks.pop(request.name, None)
        if stack is not None:
            await stack.aclose()
        logger.info("Tunnel {} destroyed", request.name)
        if self._on_tunnels_changed is not None:
            self._on_tunnels_changed(self._current_tunnels())
        return TunnelDestroyed(request_id=request.id, name=request.name), []



    async def handle_list_regions(
        self,
        request: ListRegions,
        fds: list[int],
        emit: Emit[Never],
    ) -> tuple[RegionsListed, list[int]]:
        backend_instance = get_backend(request.backend or "pia")
        regions = await backend_instance.list_regions()
        countries = [
            Country(region_id=region.id, name=region.name, country=region.country, port_forward=region.port_forward)
            for region in regions
        ]
        return RegionsListed(request_id=request.id, countries=countries), []

    async def handle_list_tunnels(
        self,
        request: ListTunnels,
        fds: list[int],
        emit: Emit[Never],
    ) -> tuple[TunnelsListed, list[int]]:
        return TunnelsListed(request_id=request.id, tunnels=self._current_tunnels()), []
