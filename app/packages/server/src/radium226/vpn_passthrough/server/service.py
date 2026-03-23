import asyncio
import json
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
    BackendInfo,
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
    ProcessInfo,
    ProcessKilled,
    ProcessRestarted,
    ProcessStarted,
    ProcessTerminated,
    PortsRebound,
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
from .dns_leak_guard import DNSLeakGuard
from .internet import Internet
from .namespace import Namespace
from .network_interfaces import NetworkInterfaces
from .vpeer_port_forward import VpeerPortForward
from .linux import make_preexec_fn

_MIN_RESTART_INTERVAL = 1.0  # seconds — prevent tight restart loops


@dataclass
class BackendConfig:
    name: str
    type: str
    credentials: dict[str, str]

    @classmethod
    def load(cls, name: str, backends_folder_path: Path) -> "BackendConfig":
        import yaml
        path = backends_folder_path / f"{name}.yaml"
        if not path.exists():
            raise LookupError(f"Backend {name!r} not configured (expected {path})")
        with path.open() as f:
            data = yaml.safe_load(f) or {}
        return cls(name=name, type=data["type"], credentials=data.get("credentials", {}))

    @classmethod
    def load_all(cls, backends_folder_path: Path) -> list["BackendConfig"]:
        if not backends_folder_path.exists():
            return []
        return [cls.load(path.stem, backends_folder_path) for path in sorted(backends_folder_path.glob("*.yaml"))]


@dataclass
class _TunnelContext:
    public_ip: str
    gateway_ip: str
    tun_ip: str
    forwarded_ports: dict[str, int]
    veth: str = ""
    veth_ip: str = ""
    vpeer: str = ""
    vpeer_ip: str = ""
    region_id: str | None = None
    forward_port: Callable[[], AbstractAsyncContextManager[int]] | None = None


class Service():

    def __init__(
        self,
        namespace_base_folder_path: Path,
        *,
        backends: list[BackendInfo] | None = None,
        default_backend_name: str | None = None,
        on_tunnels_changed: Callable[[list[TunnelInfo]], None] | None = None,
    ) -> None:
        self.namespace_base_folder_path = namespace_base_folder_path
        self._backends: list[BackendInfo] = backends or []
        self._default_backend_name = default_backend_name
        self.exit_stacks: dict[TunnelName, AsyncExitStack] = {}
        self.namespaces: dict[TunnelName, Namespace] = {}
        self.tunnel_contexts: dict[TunnelName, _TunnelContext] = {}
        self.processes: dict[TunnelName, dict[int, ProcessInfo]] = {}
        self._on_tunnels_changed = on_tunnels_changed
        self._tunnel_stop_signals: dict[TunnelName, asyncio.Future[None]] = {}
        self._tunnel_emit_fns: dict[TunnelName, Any] = {}  # Emit[TunnelStatusUpdated]
        self._tunnel_rebind_conditions: dict[TunnelName, asyncio.Condition] = {}

    @classmethod
    @asynccontextmanager
    async def create(
        cls,
        *,
        namespace_base_folder_path: Path,
        backends: list[BackendInfo] | None = None,
        default_backend_name: str | None = None,
        on_tunnels_changed: Callable[[list[TunnelInfo]], None] | None = None,
    ) -> AsyncIterator["Service"]:
        yield Service(namespace_base_folder_path, backends=backends, default_backend_name=default_backend_name, on_tunnels_changed=on_tunnels_changed)

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
                forwarded_ports=ctx.forwarded_ports if ctx is not None else {},
                veth=ctx.veth if ctx is not None else None,
                veth_ip=ctx.veth_ip if ctx is not None else None,
                vpeer=ctx.vpeer if ctx is not None else None,
                vpeer_ip=ctx.vpeer_ip if ctx is not None else None,
                processes=procs,
            ))
        return tunnels

    async def _notify_tunnel_updated(self, tunnel_name: TunnelName) -> None:
        if self._on_tunnels_changed is not None:
            self._on_tunnels_changed(self._current_tunnels())
        emit_fn = self._tunnel_emit_fns.get(tunnel_name)
        if emit_fn is not None:
            info = next((tunnel for tunnel in self._current_tunnels() if tunnel.name == tunnel_name), None)
            if info is not None:
                await emit_fn(TunnelStatusUpdated(info=info), [])

    def _resolve_backend(self, backend_name: str | None) -> tuple[Any, dict[str, str]]:
        backend_name = backend_name or self._default_backend_name
        if backend_name is None:
            raise ValueError("backend_name is required to connect to VPN")
        info = next((backend for backend in self._backends if backend.name == backend_name), None)
        if info is None:
            available = [backend.name for backend in self._backends]
            raise LookupError(f"Backend {backend_name!r} not found. Available: {available}")
        return get_backend(info.type), info.credentials

    async def _setup_tunnel(
        self,
        tunnel_name: TunnelName,
        region_id: str | None,
        names_of_ports_to_forward: list[str],
        emit: Any,
        backend_name: str | None = None,
        veth_cidr: str | None = None,
        ports_to_forward_from_vpeer_to_loopback: list[int] = [],
        client_pid: int | None = None,
    ) -> None:
        self._tunnel_rebind_conditions[tunnel_name] = asyncio.Condition()
        stack = AsyncExitStack()
        try:
            namespace = await stack.enter_async_context(Namespace.create(tunnel_name, base_folder_path=self.namespace_base_folder_path, client_pid=client_pid))
            network_interfaces = await stack.enter_async_context(NetworkInterfaces.add(namespace, cidr=veth_cidr))
            await stack.enter_async_context(Internet.share(tunnel_name, network_interfaces))
            await stack.enter_async_context(VpeerPortForward.setup(namespace, network_interfaces, ports_to_forward_from_vpeer_to_loopback))

            if region_id is not None and (backend_name is not None or self._default_backend_name is not None):
                backend_instance, credentials = self._resolve_backend(backend_name)
                session = await stack.enter_async_context(
                    backend_instance.connect(
                        tunnel_name,
                        enter_namespace=namespace.enter,
                        credentials=credentials,
                        region_id=region_id,
                    )
                )

                nameservers = list(session.dns_servers)
                await stack.enter_async_context(DNS.setup(namespace, nameservers=nameservers))
                await stack.enter_async_context(DNSLeakGuard.activate(namespace, network_interfaces))
                logger.info("DNS configured in tunnel {} (nameservers={})", tunnel_name, nameservers)
                await emit(DNSConfigured(nameservers=nameservers), [])

                forwarded_ports: dict[str, int] = {}
                for port_name in names_of_ports_to_forward:
                    port = await stack.enter_async_context(session.forward_port())
                    forwarded_ports[port_name] = port
                remote_ip = await self._fetch_remote_ip(namespace)
                logger.info("Connected to VPN in tunnel {} (gateway={}, remote_ip={})", tunnel_name, session.gateway_ip, remote_ip)
                await emit(ConnectedToVPN(remote_ip=remote_ip, gateway_ip=session.gateway_ip, tun_ip=session.tun_ip, forwarded_ports=forwarded_ports), [])
                self.tunnel_contexts[tunnel_name] = _TunnelContext(
                    public_ip=remote_ip,
                    gateway_ip=session.gateway_ip,
                    tun_ip=session.tun_ip,
                    forwarded_ports=forwarded_ports,
                    veth=network_interfaces.veth,
                    veth_ip=network_interfaces.veth_ip,
                    vpeer=network_interfaces.vpeer,
                    vpeer_ip=network_interfaces.vpeer_ip,
                    region_id=region_id,
                    forward_port=session.forward_port,
                )
            else:
                await stack.enter_async_context(DNS.setup(namespace, nameservers=None))
                await emit(DNSConfigured(nameservers=[]), [])
                self.tunnel_contexts[tunnel_name] = _TunnelContext(
                    public_ip="",
                    gateway_ip="",
                    tun_ip="",
                    forwarded_ports={},
                    veth=network_interfaces.veth,
                    veth_ip=network_interfaces.veth_ip,
                    vpeer=network_interfaces.vpeer,
                    vpeer_ip=network_interfaces.vpeer_ip,
                )

            self.namespaces[tunnel_name] = namespace
            self.exit_stacks[tunnel_name] = stack
        except BaseException:
            self.tunnel_contexts.pop(tunnel_name, None)
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

        if request.tunnel_name is None:
            raise ValueError("RunProcess requires tunnel_name")
        if request.username is None:
            raise ValueError("RunProcess requires username")

        tunnel_name = request.tunnel_name
        if tunnel_name not in self.namespaces:
            logger.info("Lazily creating tunnel {} for process", tunnel_name)
            await self._setup_tunnel(tunnel_name, None, [], emit, client_pid=request.client_pid)

        namespace = self.namespaces[tunnel_name]

        preexec_fn, close_parent_fds = make_preexec_fn(
            request.username,
            namespace.pid,
            cwd=request.cwd,
            client_pid=request.client_pid,
        )

        first = True
        self.processes.setdefault(tunnel_name, {})

        while True:
            ctx = self.tunnel_contexts.get(tunnel_name)
            jinja_vars = {
                "public_ip": ctx.public_ip if ctx is not None else "",
                "gateway_ip": ctx.gateway_ip if ctx is not None else "",
                "tun_ip": ctx.tun_ip if ctx is not None else "",
                "forwarded_ports": ctx.forwarded_ports if ctx is not None else {},
                "veth": ctx.veth if ctx is not None else "",
                "veth_ip": ctx.veth_ip if ctx is not None else "",
                "vpeer": ctx.vpeer if ctx is not None else "",
                "vpeer_ip": ctx.vpeer_ip if ctx is not None else "",
            }
            try:
                command = Template(request.command).render(**jinja_vars)
                args = [Template(arg).render(**jinja_vars) for arg in request.args]
            except TemplateError as e:
                logger.error("Jinja2 template error in command: {}", e)
                close_parent_fds()
                for fd in (stdin_fd, stdout_fd, stderr_fd):
                    try:
                        os.close(fd)
                    except OSError as close_err:
                        logger.warning("Failed to close fd {}: {}", fd, close_err)
                return CommandNotFound(request_id=request.id, command=request.command), []

            if request.configure_with is not None:
                payload = {
                    "first": first,
                    "public_ip": ctx.public_ip if ctx is not None else None,
                    "gateway_ip": ctx.gateway_ip if ctx is not None else None,
                    "tun_ip": ctx.tun_ip if ctx is not None else None,
                    "forwarded_ports": ctx.forwarded_ports if ctx is not None else {},
                    "veth": ctx.veth if ctx is not None else None,
                    "veth_ip": ctx.veth_ip if ctx is not None else None,
                    "vpeer": ctx.vpeer if ctx is not None else None,
                    "vpeer_ip": ctx.vpeer_ip if ctx is not None else None,
                }
                try:
                    configure_proc = await asyncio.create_subprocess_exec(
                        request.configure_with,
                        stdin=asyncio.subprocess.PIPE,
                    )
                    await configure_proc.communicate(json.dumps(payload).encode())
                    if configure_proc.returncode != 0:
                        def _close_fds() -> None:
                            close_parent_fds()
                            for fd in (stdin_fd, stdout_fd, stderr_fd):
                                try:
                                    os.close(fd)
                                except OSError as close_err:
                                    logger.warning("Failed to close fd {}: {}", fd, close_err)
                        if first:
                            logger.error(
                                "configure-with script {} failed on first start (exit code {}), aborting",
                                request.configure_with,
                                configure_proc.returncode,
                            )
                            _close_fds()
                            return ProcessTerminated(request_id=request.id, exit_code=configure_proc.returncode or 1), []
                        else:
                            logger.info(
                                "configure-with script {} returned {}, not restarting process",
                                request.configure_with,
                                configure_proc.returncode,
                            )
                            _close_fds()
                            return ProcessTerminated(request_id=request.id, exit_code=0), []
                except FileNotFoundError:
                    logger.error("configure-with script not found: {}", request.configure_with)
                except Exception as e:
                    logger.error("configure-with script failed: {}", e)

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
                close_parent_fds()
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
                ports = ctx.forwarded_ports if ctx is not None else {}
                logger.debug("Process restarted with pid {} (forwarded_ports={})", process.pid, ports)
                await emit(ProcessRestarted(pid=process.pid, forwarded_ports=ports), [])

            rebind_condition = self._tunnel_rebind_conditions.get(tunnel_name)
            if rebind_condition is not None:
                async def _wait_for_tunnel_rebind(cond: asyncio.Condition) -> None:
                    async with cond:
                        await cond.wait()
                wait_task = asyncio.create_task(process.wait())
                rebind_task = asyncio.create_task(_wait_for_tunnel_rebind(rebind_condition))
                done, _ = await asyncio.wait(
                    [wait_task, rebind_task],
                    return_when=asyncio.FIRST_COMPLETED,
                )
                wait_task.cancel()
                rebind_task.cancel()
                if rebind_task in done:
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

        close_parent_fds()
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
    async def _fetch_remote_ip(namespace: Namespace) -> str:
        process = await asyncio.create_subprocess_exec(
            "curl", "ifconfig.me",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            preexec_fn=namespace.enter,
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
        await self._setup_tunnel(request.name, request.region_id, request.names_of_ports_to_forward, emit, backend_name=request.backend_name, veth_cidr=request.veth_cidr, ports_to_forward_from_vpeer_to_loopback=request.ports_to_forward_from_vpeer_to_loopback)
        logger.info("Tunnel {} created", request.name)
        if self._on_tunnels_changed is not None:
            self._on_tunnels_changed(self._current_tunnels())
        tunnel_info = next((tunnel for tunnel in self._current_tunnels() if tunnel.name == request.name), TunnelInfo(name=request.name))
        return TunnelCreated(request_id=request.id, name=request.name, tunnel=tunnel_info), []

    async def handle_start_tunnel(
        self,
        request: StartTunnel,
        fds: list[int],
        emit: Emit[ConfigUsed | TunnelStarted | ConnectedToVPN | DNSConfigured | TunnelStatusUpdated | PortsRebound],
    ) -> tuple[TunnelStopped, list[int]]:
        await emit(ConfigUsed(
            region_id=request.region_id,
            backend_name=request.backend_name,
            names_of_ports_to_forward=request.names_of_ports_to_forward,
        ), [])
        await self._setup_tunnel(request.name, request.region_id, request.names_of_ports_to_forward, emit, backend_name=request.backend_name, veth_cidr=request.veth_cidr, ports_to_forward_from_vpeer_to_loopback=request.ports_to_forward_from_vpeer_to_loopback)
        logger.info("Tunnel {} started", request.name)
        if self._on_tunnels_changed is not None:
            self._on_tunnels_changed(self._current_tunnels())
        await emit(TunnelStarted(name=request.name), [])

        self._tunnel_emit_fns[request.name] = emit
        loop = asyncio.get_running_loop()
        stop: asyncio.Future[None] = loop.create_future()
        self._tunnel_stop_signals[request.name] = stop

        rebind_task: asyncio.Task[None] | None = None
        if request.rebind_ports_every is not None:
            rebind_every = max(request.rebind_ports_every, _MIN_RESTART_INTERVAL)

            async def _rebind_loop() -> None:
                while True:
                    await asyncio.sleep(rebind_every)
                    ctx = self.tunnel_contexts.get(request.name)
                    if ctx is None or ctx.forward_port is None:
                        break
                    new_ports: dict[str, int] = {}
                    for port_name in ctx.forwarded_ports:
                        new_port = await self.exit_stacks[request.name].enter_async_context(ctx.forward_port())
                        new_ports[port_name] = new_port
                    self.tunnel_contexts[request.name] = _TunnelContext(
                        public_ip=ctx.public_ip,
                        gateway_ip=ctx.gateway_ip,
                        tun_ip=ctx.tun_ip,
                        forwarded_ports=new_ports,
                        veth=ctx.veth,
                        veth_ip=ctx.veth_ip,
                        vpeer=ctx.vpeer,
                        vpeer_ip=ctx.vpeer_ip,
                        region_id=ctx.region_id,
                        forward_port=ctx.forward_port,
                    )
                    logger.info("Rebound ports for tunnel {} (new_ports={})", request.name, new_ports)
                    await emit(PortsRebound(forwarded_ports=new_ports), [])
                    await self._notify_tunnel_updated(request.name)
                    condition = self._tunnel_rebind_conditions.get(request.name)
                    if condition is not None:
                        async with condition:
                            condition.notify_all()

            rebind_task = asyncio.create_task(_rebind_loop())

        try:
            await stop
        finally:
            if rebind_task is not None:
                rebind_task.cancel()
                try:
                    await rebind_task
                except asyncio.CancelledError:
                    pass
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
        self._tunnel_rebind_conditions.pop(request.name, None)

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
        backend_instance, _ = self._resolve_backend(request.backend_name)
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
