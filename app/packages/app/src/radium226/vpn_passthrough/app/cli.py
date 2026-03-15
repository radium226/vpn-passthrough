import asyncio
import fcntl
import functools
import json
import os
import pty
import random
import signal
import struct
import termios
import tty
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import AsyncIterator

import click
import yaml
from loguru import logger
from prettytable import PrettyTable

from radium226.vpn_passthrough.server import Server
from radium226.vpn_passthrough.client import Client
from radium226.vpn_passthrough.messages import ConfigUsed, PortsRebound, Tunnel
from radium226.vpn_passthrough.messages import TunnelInfo
from radium226.vpn_passthrough.app.config import Config, TUNNEL_CONFIGS_DIR
from radium226.vpn_passthrough.app.systemd import sd_notify


def pass_config(f):
    @functools.wraps(f)
    def new_func(*args, **kwargs):
        ctx = click.get_current_context()
        return ctx.invoke(f, ctx.obj.config, *args, **kwargs)
    return functools.update_wrapper(new_func, f)


@click.group()
@click.option(
    "--socket",
    "socket_file_path",
    type=Path,
    default=None,
    envvar="VPN_PASSTHROUGH_SOCKET",
    help="Path to the Unix domain socket (overrides config file).",
)
@click.option(
    "--config",
    "-c",
    "config_file_path",
    type=Path,
    default=None,
    help="Path to an extra config file merged on top of system/user configs.",
)
@click.option("--skip-user-config", "skip_user_config", is_flag=True, default=False, help="Skip XDG user config files.")
@click.pass_context
def app(ctx: click.Context, socket_file_path: Path | None, config_file_path: Path | None, skip_user_config: bool) -> None:
    ctx.ensure_object(SimpleNamespace)
    skip_user_config = skip_user_config or ctx.invoked_subcommand == "start-server"
    cli_config = Config() if socket_file_path is None else Config(socket_file_path=socket_file_path)
    ctx.obj.config = Config.load(config_file_path, skip_user_config=skip_user_config).merge_with(cli_config)


def _parse_credential(value: str) -> tuple[str, str]:
    if "=" not in value:
        raise click.BadParameter(f"Credential must be in key=value format, got: {value!r}")
    key, _, val = value.partition("=")
    return key, val


@asynccontextmanager
async def _ensure_tunnel(
    client: Client,
    tunnel_name: str | None,
    region_id: str | None,
    credentials: dict[str, str] | None,
    backend: str | None,
) -> AsyncIterator[str]:
    """Yield a tunnel name, creating (and later destroying) a temporary one when tunnel_name is None."""
    if tunnel_name is not None:
        yield tunnel_name
        return

    temp_name = str(uuid.uuid4())
    resolved_region_id = region_id
    if credentials is not None and region_id is None:
        countries = await client.list_regions(backend=backend)
        chosen = random.choice(countries)
        click.echo(f"No region specified, randomly chose: {chosen.name} ({chosen.region_id})")
        resolved_region_id = chosen.region_id
    await client.create_tunnel(temp_name, region_id=resolved_region_id, credentials=credentials, backend=backend)
    try:
        yield temp_name
    finally:
        await client.destroy_tunnel(temp_name)


async def _proxy_pty(master_fd: int) -> None:
    """Forward bytes between the real terminal and the PTY master until cancelled or an I/O error."""
    loop = asyncio.get_running_loop()
    done: asyncio.Future[None] = loop.create_future()

    def _read_stdin() -> None:
        try:
            data = os.read(0, 4096)
            if data:
                os.write(master_fd, data)
        except OSError:
            if not done.done():
                done.set_result(None)

    def _read_master() -> None:
        try:
            data = os.read(master_fd, 4096)
            if data:
                os.write(1, data)
        except OSError:
            if not done.done():
                done.set_result(None)

    loop.add_reader(0, _read_stdin)
    loop.add_reader(master_fd, _read_master)
    try:
        await done
    except asyncio.CancelledError:
        pass
    finally:
        loop.remove_reader(0)
        loop.remove_reader(master_fd)


def _on_tunnels_changed(tunnels: list[TunnelInfo]) -> None:
    n = len(tunnels)
    if n == 0:
        status = "No tunnel created"
    else:
        parts = [t.region_id or t.name for t in tunnels]
        word = "tunnel" if n == 1 else "tunnels"
        status = f"{n} {word} created ({', '.join(parts)})"
    sd_notify(f"STATUS={status}")


@app.command("start-server")
@pass_config
def start_server(config: Config) -> None:
    async def _run() -> None:
        async with Server.listen(
            config.socket_file_path,
            config.namespace_base_folder_path,
            on_tunnels_changed=_on_tunnels_changed,
        ) as server:
            _on_tunnels_changed([])
            await server.wait_forever()

    asyncio.run(_run())


@app.command("run-process")
@click.option(
    "--kill-with",
    type=int,
    default=None,
    help="Signal to use when killing the process for restart (default: SIGTERM).",
)
@click.option(
    "--in-tunnel",
    "tunnel_name",
    default=None,
    help="Run the process inside the named tunnel. If omitted, a temporary tunnel is created and destroyed on exit.",
)
@click.option("--region-id", default=None, envvar="VPN_PASSTHROUGH_REGION_ID", help="VPN region ID for the temporary tunnel.")
@click.option("--credential", "credential_items", multiple=True, help="VPN credential as key=value (repeatable, overrides config file).")
@click.option("--vpn-backend", "vpn_backend", default=None, envvar="VPN_PASSTHROUGH_BACKEND", help="VPN backend name (default: pia).")
@click.option("--configure-with", "configure_with", default=None, type=click.Path(), help="Script to run after port rebind and before process restart; receives tunnel context as JSON on stdin.")
@click.argument("command", nargs=-1, required=True)
@pass_config
def run_process(config: Config, kill_with: int | None, tunnel_name: str | None, region_id: str | None, credential_items: tuple[str, ...], vpn_backend: str | None, configure_with: str | None, command: tuple[str, ...]) -> None:
    credentials = dict(_parse_credential(c) for c in credential_items) if credential_items else config.vpn_credentials
    backend = vpn_backend or config.vpn_backend

    async def _run() -> None:
        loop = asyncio.get_running_loop()
        pid_future: asyncio.Future[int] = loop.create_future()

        async with Client.connect(config.socket_file_path) as client:
            async with _ensure_tunnel(client, tunnel_name, region_id, credentials, backend) as effective_tunnel_name:
                async def handle_pid(pid: int) -> None:
                    if not pid_future.done():
                        pid_future.set_result(pid)

                def forward_signal(sig: signal.Signals) -> None:
                    async def _kill() -> None:
                        pid = await pid_future
                        await client.kill_process(pid, sig)
                    asyncio.create_task(_kill())

                for sig in (signal.SIGINT, signal.SIGTERM):
                    loop.add_signal_handler(sig, forward_signal, sig)

                try:
                    exit_code = await client.run_process(
                        command[0],
                        list(command[1:]),
                        fds=[os.dup(0), os.dup(1), os.dup(2)],
                        kill_with=kill_with,
                        in_tunnel=Tunnel(name=effective_tunnel_name),
                        cwd=str(Path.cwd()),
                        gid=os.getgid(),
                        on_pid_received=handle_pid,
                        configure_with=configure_with,
                    )
                finally:
                    for sig in (signal.SIGINT, signal.SIGTERM):
                        loop.remove_signal_handler(sig)

        raise SystemExit(exit_code)

    asyncio.run(_run())


@app.command("debug-tunnel")
@click.option(
    "--in-tunnel",
    "tunnel_name",
    default=None,
    help="Run bash inside the named tunnel. If omitted, a temporary tunnel is created and destroyed on exit.",
)
@click.option("--region-id", default=None, envvar="VPN_PASSTHROUGH_REGION_ID", help="VPN region ID for the temporary tunnel.")
@click.option("--credential", "credential_items", multiple=True, help="VPN credential as key=value (repeatable, overrides config file).")
@click.option("--vpn-backend", "vpn_backend", default=None, envvar="VPN_PASSTHROUGH_BACKEND", help="VPN backend name (default: pia).")
@pass_config
def debug_tunnel(config: Config, tunnel_name: str | None, region_id: str | None, credential_items: tuple[str, ...], vpn_backend: str | None) -> None:
    credentials = dict(_parse_credential(c) for c in credential_items) if credential_items else config.vpn_credentials
    backend = vpn_backend or config.vpn_backend

    async def _run() -> None:
        loop = asyncio.get_running_loop()

        master_fd, slave_fd = pty.openpty()

        # Mirror the real terminal size into the PTY slave
        try:
            cols, rows = os.get_terminal_size(0)
            fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        except OSError:
            pass

        def _sync_winsize() -> None:
            try:
                cols, rows = os.get_terminal_size(0)
                fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
            except OSError:
                pass

        loop.add_signal_handler(signal.SIGWINCH, _sync_winsize)

        # Raw mode: every keystroke goes straight to the PTY master
        is_tty = os.isatty(0)
        old_settings = termios.tcgetattr(0) if is_tty else None
        if is_tty:
            tty.setraw(0)

        proxy_task: asyncio.Task[None] | None = None
        exit_code = 1
        try:
            async with Client.connect(config.socket_file_path) as client:
                async with _ensure_tunnel(client, tunnel_name, region_id, credentials, backend) as effective_tunnel_name:
                    proxy_task = asyncio.create_task(_proxy_pty(master_fd))
                    exit_code = await client.run_process(
                        "bash",
                        [],
                        # All three stdio fds point to the PTY slave; SCM_RIGHTS
                        # dups them independently in the server process.
                        fds=[slave_fd, slave_fd, slave_fd],
                        in_tunnel=Tunnel(name=effective_tunnel_name),
                        cwd=str(Path.cwd()),
                        # Do NOT drop to user's uid/gid: setuid() clears all capability
                        # sets, and even if ping's file capabilities can restore
                        # CAP_NET_RAW via the bounding set, a restricted bounding set
                        # (e.g. from a systemd service) will silently break it.
                        # Running as root inside the isolated network namespace is safe
                        # because the tunnel provides full network-stack isolation.
                    )
        finally:
            if proxy_task is not None:
                proxy_task.cancel()
                try:
                    await proxy_task
                except asyncio.CancelledError:
                    pass
            loop.remove_signal_handler(signal.SIGWINCH)
            os.close(slave_fd)
            os.close(master_fd)
            if is_tty and old_settings is not None:
                termios.tcsetattr(0, termios.TCSADRAIN, old_settings)

        raise SystemExit(exit_code)

    asyncio.run(_run())


@app.command("create-tunnel")
@click.option("--region-id", default=None, envvar="VPN_PASSTHROUGH_REGION_ID", help="VPN region ID. If omitted, falls back to config file, then a random region is chosen.")
@click.option("--credential", "credential_items", multiple=True, help="VPN credential as key=value (repeatable, overrides config file).")
@click.option("--vpn-backend", "vpn_backend", default=None, envvar="VPN_PASSTHROUGH_BACKEND", help="VPN backend name (default: pia).")
@click.option("--without-vpn", "without_vpn", is_flag=True, default=False, help="Create the tunnel without connecting to VPN.")
@click.option("--forward-port-for", "names_of_ports_to_forward", multiple=True, help="Forward a port with the given name (repeatable, e.g. --forward-port-for transmission).")
@click.option("--veth-cidr", "veth_cidr", default=None, help="Fixed CIDR for the veth pair (e.g. 10.200.5.0/24). If omitted, an address is derived from the tunnel name.")
@click.argument("name")
@pass_config
def create_tunnel(config: Config, region_id: str | None, credential_items: tuple[str, ...], vpn_backend: str | None, without_vpn: bool, names_of_ports_to_forward: tuple[str, ...], veth_cidr: str | None, name: str) -> None:
    config = config.merge_with(Config._from_file(TUNNEL_CONFIGS_DIR / f"{name}.yaml"))
    credentials = dict(_parse_credential(c) for c in credential_items) if credential_items else config.vpn_credentials
    backend = vpn_backend or config.vpn_backend
    region_id = region_id or config.region_id
    resolved_names = list(names_of_ports_to_forward) if names_of_ports_to_forward else config.names_of_ports_to_forward

    async def _run() -> None:
        async with Client.connect(config.socket_file_path) as client:
            if without_vpn:
                resolved_region_id, resolved_credentials = None, None
            elif credentials is not None and region_id is None:
                countries = await client.list_regions(backend=backend)
                if resolved_names:
                    countries = [c for c in countries if c.port_forward]
                chosen = random.choice(countries)
                click.echo(f"No region specified, randomly chose: {chosen.name} ({chosen.region_id})")
                resolved_region_id, resolved_credentials = chosen.region_id, credentials
            else:
                resolved_region_id, resolved_credentials = region_id, credentials

            loop = asyncio.get_running_loop()
            stop: asyncio.Future[None] = loop.create_future()

            def _stop() -> None:
                if not stop.done():
                    stop.set_result(None)

            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, _stop)

            created = False
            try:
                await client.create_tunnel(name, region_id=resolved_region_id, credentials=resolved_credentials, names_of_ports_to_forward=resolved_names, backend=backend, veth_cidr=veth_cidr)
                created = True
                await stop
            finally:
                for sig in (signal.SIGINT, signal.SIGTERM):
                    loop.remove_signal_handler(sig)
                if created:
                    await client.destroy_tunnel(name)

    asyncio.run(_run())


@app.command("start-tunnel")
@click.option("--region-id", default=None, envvar="VPN_PASSTHROUGH_REGION_ID", help="VPN region ID. If omitted, falls back to config, then a random region is chosen.")
@click.option("--credential", "credential_items", multiple=True, help="VPN credential as key=value (repeatable, overrides config file).")
@click.option("--vpn-backend", "vpn_backend", default=None, envvar="VPN_PASSTHROUGH_BACKEND", help="VPN backend name (default: pia).")
@click.option("--without-vpn", "without_vpn", is_flag=True, default=False, help="Start the tunnel without connecting to VPN.")
@click.option("--forward-port-for", "names_of_ports_to_forward", multiple=True, help="Forward a port with the given name (repeatable, e.g. --forward-port-for transmission).")
@click.option("--rebind-ports-every", "rebind_ports_every", type=float, default=None, help="Reallocate forwarded ports every N seconds (default: from config).")
@click.option("--persistent", "persistent", is_flag=True, default=False, help=f"Write the resolved tunnel config to {TUNNEL_CONFIGS_DIR}/<name>.yaml so future invocations reuse it.")
@click.option("--veth-cidr", "veth_cidr", default=None, help="Fixed CIDR for the veth pair (e.g. 10.200.5.0/24). If omitted, an address is derived from the tunnel name.")
@click.argument("name")
@pass_config
def start_tunnel(config: Config, region_id: str | None, credential_items: tuple[str, ...], vpn_backend: str | None, without_vpn: bool, names_of_ports_to_forward: tuple[str, ...], rebind_ports_every: float | None, persistent: bool, veth_cidr: str | None, name: str) -> None:
    config = config.merge_with(Config._from_file(TUNNEL_CONFIGS_DIR / f"{name}.yaml"))
    credentials = dict(_parse_credential(c) for c in credential_items) if credential_items else config.vpn_credentials
    backend = vpn_backend or config.vpn_backend
    region_id = region_id or config.region_id
    resolved_names = list(names_of_ports_to_forward) if names_of_ports_to_forward else config.names_of_ports_to_forward
    rebind_ports_every = rebind_ports_every if rebind_ports_every is not None else config.port_rebind_every

    async def _run() -> None:
        async with Client.connect(config.socket_file_path) as client:
            if without_vpn:
                resolved_region_id, resolved_credentials = None, None
            elif credentials is not None and region_id is None:
                countries = await client.list_regions(backend=backend)
                if resolved_names:
                    countries = [c for c in countries if c.port_forward]
                chosen = random.choice(countries)
                click.echo(f"No region specified, randomly chose: {chosen.name} ({chosen.region_id})")
                resolved_region_id, resolved_credentials = chosen.region_id, credentials
            else:
                resolved_region_id, resolved_credentials = region_id, credentials

            if persistent:
                tunnel_config_path = TUNNEL_CONFIGS_DIR / f"{name}.yaml"
                if tunnel_config_path.exists():
                    logger.warning("Tunnel config {} already exists, overwriting", tunnel_config_path)
                tunnel_config_path.parent.mkdir(parents=True, exist_ok=True)
                data: dict = {}
                if resolved_region_id is not None:
                    data["region_id"] = resolved_region_id
                if resolved_credentials is not None:
                    data["vpn_credentials"] = resolved_credentials
                if backend is not None:
                    data["vpn_backend"] = backend
                if resolved_names:
                    data["names_of_ports_to_forward"] = resolved_names
                with tunnel_config_path.open("w") as f:
                    yaml.dump(data, f, default_flow_style=False)
                logger.info("Wrote tunnel config to {}", tunnel_config_path)

            loop = asyncio.get_running_loop()
            stopping = False

            def on_ready() -> None:
                sd_notify("READY=1")

            def on_config_used(config_used: ConfigUsed) -> None:
                lines = [
                    f"  backend:                  {config_used.backend or 'pia (default)'}",
                    f"  region_id:                {config_used.region_id or '(none)'}",
                    f"  names_of_ports_to_forward:  {config_used.names_of_ports_to_forward}",
                ]
                if config_used.credentials:
                    for key, value in config_used.credentials.items():
                        masked = value[:2] + "***" if len(value) > 2 else "***"
                        lines.append(f"  credentials.{key}:          {masked}")
                else:
                    lines.append("  credentials:              (none)")
                click.echo("Config used:\n" + "\n".join(lines))

            def on_tunnel_status_updated(info: TunnelInfo) -> None:
                n = len(info.processes)
                word = "process" if n == 1 else "processes"
                sd_notify(f"STATUS={n} {word} running")

            def on_ports_rebound(event: PortsRebound) -> None:
                parts = ", ".join(f"{k}={v}" for k, v in event.forwarded_ports.items())
                click.echo(f"Ports rebound: {parts}")

            def _stop(sig: signal.Signals) -> None:
                nonlocal stopping
                if stopping:
                    return
                stopping = True
                logger.warning("Received {}, stopping tunnel {}", sig.name, name)
                asyncio.create_task(client.destroy_tunnel(name))

            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, _stop, sig)
            try:
                await client.start_tunnel(
                    name,
                    region_id=resolved_region_id,
                    credentials=resolved_credentials,
                    names_of_ports_to_forward=resolved_names,
                    backend=backend,
                    rebind_ports_every=rebind_ports_every,
                    veth_cidr=veth_cidr,
                    on_ready=on_ready,
                    on_config_used=on_config_used,
                    on_tunnel_status_updated=on_tunnel_status_updated,
                    on_ports_rebound=on_ports_rebound,
                )
            finally:
                for sig in (signal.SIGINT, signal.SIGTERM):
                    loop.remove_signal_handler(sig)

    asyncio.run(_run())


@app.command("list-regions")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["table", "json"]),
    default="table",
    help="Output format.",
)
@click.option("--vpn-backend", "vpn_backend", default=None, envvar="VPN_PASSTHROUGH_BACKEND", help="VPN backend name (default: pia).")
@pass_config
def list_regions(config: Config, output_format: str, vpn_backend: str | None) -> None:
    backend = vpn_backend or config.vpn_backend
    async def _run() -> None:
        async with Client.connect(config.socket_file_path) as client:
            countries = await client.list_regions(backend=backend)

            if output_format == "json":
                click.echo(json.dumps(
                    [{"region_id": c.region_id, "name": c.name, "country": c.country} for c in countries],
                    indent=2,
                ))
            else:
                table = PrettyTable()
                table.field_names = ["Region ID", "Name", "Country"]
                table.align = "l"
                for c in countries:
                    table.add_row([c.region_id, c.name, c.country])
                click.echo(table)

    asyncio.run(_run())


@app.command("list-tunnels")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["table", "json"]),
    default="table",
    help="Output format.",
)
@click.option("--with-processes", "with_processes", is_flag=True, default=False, help="Include running processes per tunnel.")
@pass_config
def list_tunnels(config: Config, output_format: str, with_processes: bool) -> None:
    async def _run() -> None:
        async with Client.connect(config.socket_file_path) as client:
            tunnels = await client.list_tunnels()

            if output_format == "json":
                click.echo(json.dumps(
                    [
                        {
                            "name": t.name,
                            "vpn_connected": t.vpn_connected,
                            "region_id": t.region_id,
                            "public_ip": t.public_ip,
                            "gateway_ip": t.gateway_ip,
                            "tun_ip": t.tun_ip,
                            "forwarded_ports": t.forwarded_ports,
                            **({"processes": [{"pid": p.pid, "command": p.command, "args": p.args} for p in t.processes]} if with_processes else {}),
                        }
                        for t in tunnels
                    ],
                    indent=2,
                ))
            else:
                fields = ["Name", "VPN", "Region", "Public IP", "Gateway IP", "Tun IP", "Forwarded Ports"]
                if with_processes:
                    fields.append("Processes")
                table = PrettyTable()
                table.field_names = fields
                table.align = "l"
                for t in tunnels:
                    row = [
                        t.name,
                        "yes" if t.vpn_connected else "no",
                        t.region_id or "",
                        t.public_ip or "",
                        t.gateway_ip or "",
                        t.tun_ip or "",
                        ", ".join(f"{k}={v}" for k, v in t.forwarded_ports.items()),
                    ]
                    if with_processes:
                        row.append("\n".join(f"{p.pid}: {p.command} {' '.join(p.args)}".strip() for p in t.processes))
                    table.add_row(row)
                click.echo(table)

    asyncio.run(_run())


@app.command("list-backends")
def list_backends_cmd() -> None:
    from radium226.vpn_passthrough.vpn import list_backends
    for name in list_backends():
        click.echo(name)


@app.command("show-config")
@click.option("--empty", "empty", is_flag=True, default=False, help="Show default config values instead of the loaded config.")
@pass_config
def show_config(config: Config, empty: bool) -> None:
    click.echo(yaml.dump((Config() if empty else config).model_dump(mode="json"), default_flow_style=False), nl=False)


@app.command("destroy-tunnel")
@click.argument("name")
@pass_config
def destroy_tunnel(config: Config, name: str) -> None:
    async def _run() -> None:
        async with Client.connect(config.socket_file_path) as client:
            await client.destroy_tunnel(name)

    asyncio.run(_run())
