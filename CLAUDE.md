# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

VPN passthrough — a system for executing commands through a daemon over Unix domain sockets with file descriptor passing (`SCM_RIGHTS`). The repo is a monorepo with packages under `app/packages/`.

## Monorepo Structure

- **app/packages/ipc** — IPC library: async Unix socket transport, generic `Request[ResponseT, EventT]` protocol with `Codec`, `Server`/`Client` classes, request correlation via `id`/`request_id`, and event multiplexing. Exports `IPCServer` and `IPCClient`. Namespace: `radium226.vpn_passthrough.ipc`.
- **app/packages/messages** — Protocol message types: all requests, responses, events, data models, and `CODEC` for serialization. Namespace: `radium226.vpn_passthrough.messages`.
- **app/packages/server** — Daemon/server logic: `Service` class with all handlers, netns support (`netns.py`, `network_interfaces.py`, `dns.py`, `dns_leak_guard.py`, `internet.py`). `Server` class with `Server.listen(config)` context manager and `wait_forever()`. Exports `Server`, `ServerConfig`, `BackendConfig`. Namespace: `radium226.vpn_passthrough.server`.
- **app/packages/client** — High-level client: `Client` class with `Client.connect(config)` context manager, `run_process()`, `kill_process()`, `create_tunnel()`, `start_tunnel()`, `destroy_tunnel()`, `list_regions()`, `list_tunnels()`, `lookup_tunnel()`. Exports `Client`, `ClientConfig`, `TunnelConfig`. Namespace: `radium226.vpn_passthrough.client`.
- **app/packages/app** — CLI application: `vpn-passthrough` binary with `start-server`, `start-tunnel`, `create-tunnel`, `destroy-tunnel`, `run-process`, `debug-tunnel`, `list-tunnels`, `list-regions`, `list-backends`, `show-config` commands. Global option: `--config FOLDER` (env: `VPN_PASSTHROUGH_CONFIG`). Config is folder-based: `server.yaml`, `client.yaml`, and `tunnels/*.yaml` are loaded from the config folder (default `/etc/vpn-passthrough`). Depends on server and client.
- **app/packages/vpn** — VPN backend protocol: `Backend` protocol class with `connect()` and `list_regions()`, `Session` dataclass with `forward_port()` context manager, `Region` dataclass. Backend discovery via `vpn_passthrough.vpn_backends` entry points. Namespace: `radium226.vpn_passthrough.vpn`.
- **app/packages/pia** — PIA VPN backend: connects a Linux network namespace to Private Internet Access via OpenVPN. Implements the `Backend` protocol. Standalone (no workspace deps, only `loguru` + `httpx`). Namespace: `radium226.vpn_passthrough.pia`.
- **app/packages/dummy** — Dummy VPN backend for testing: returns fake IPs and a single dummy region. Namespace: `radium226.vpn_passthrough.dummy`.
- **packages/arch** — Arch Linux packaging: `PKGBUILD` that builds all workspace packages, systemd units, sysusers/tmpfiles fragments, and default config files.

Dependency chain: `app → server, client → messages → ipc`; `server → vpn`; `pia` and `dummy` implement `vpn`'s `Backend` protocol via entry points; `pia` is independent of the IPC stack.

## Commands

Each package is independent — **`cd` into the package directory** before running commands.

```bash
cd app/packages/ipc   # or messages, server, client, app, vpn, pia, dummy

uv sync                                          # Install deps
mise run check                                   # Run ty + ruff + pytest
uv run ty check                                  # Type check only
uv run ruff check                                # Lint only
uv run python -m pytest                          # Run all tests
uv run python -m pytest tests/test_transport.py::test_name  # Run a single test
```

## Tech Stack

- Python 3.13, uv (build/package manager), mise (task runner)
- pydantic for message serialization, click for CLI, loguru for logging
- pytest + pytest-asyncio for tests, ruff for linting, ty for type checking

## Configuration

Config is folder-based. The default folder is `/etc/vpn-passthrough` containing:
- `server.yaml` — `ServerConfig` fields: `socket_file_path`, `namespace_base_folder_path`, `backends_folder_path`, `default_backend_name`
- `client.yaml` — `ClientConfig` fields: `socket_file_path`
- `tunnels/*.yaml` — per-tunnel `TunnelConfig`: `name`, `region_id`, `names_of_ports_to_forward`, `backend_name`, `veth_cidr`, `rebind_ports_every`, `ports_to_forward_from_vpeer_to_loopback`

Override with `--config FOLDER` or `VPN_PASSTHROUGH_CONFIG` env var.

## Architecture Details

### IPC Package (app/packages/ipc)

Three layers — **transport**, **protocol**, and **server/client**:

- **Transport** (`transport.py`): `Connection` class wrapping a non-blocking Unix socket with `send_frame`/`receive_frame` using `Framing` protocol (default: `NullCharFraming` with `\0` delimiter). `Frame` = bytes + fd list. `accept_connections()` and `open_connection()` for server/client socket setup.
- **Protocol** (`protocol.py`): Generic `Request[ResponseT, EventT]` base class with phantom types resolved at class creation via `__init_subclass__`. `Response` structural protocol (has `request_id`). `Codec` dataclass with `encode`/`decode`. `ResponseHandler` bundles `on_event` and `on_response` callbacks.
- **Server** (`server.py`): Generic `Server` class handling connections, decoding frames, dispatching requests to registered handlers, emitting events, and sending responses. `RequestHandler` dataclass (defined in `protocol.py`) bundles a `request_type` with an async `on_request` callback. `Server.listen()` starts the serve task and waits for the socket file to appear. Exported as `IPCServer`.
- **Client** (`client.py`): Generic `Client` class with `request()` method that sends a request, registers a `ResponseHandler`, and awaits completion. Background `_receive_loop` routes responses and events to pending handlers. `Client.connect()` is the async context manager entry point. Exported as `IPCClient`.
- **IPC** (`ipc.py`): Thin wrappers `open_server()` and `open_client()` delegating to `IPCServer.listen()` and `IPCClient.connect()`.

### Messages Package (app/packages/messages)

- `__init__.py` — Pydantic message types:
  - **Requests:**
    - `RunProcess(Request[ProcessTerminated | CommandNotFound, ProcessStarted | ProcessRestarted])` with `kill_with`, `tunnel_name`, `cwd`, `username`, `gid`, `ambient_capabilities`, `configure_with` params; `command` and `args` support Jinja2 template variables (`public_ip`, `gateway_ip`, `tun_ip`, `forwarded_ports`) resolved from tunnel context at spawn time
    - `KillProcess(Request[ProcessKilled, Never])`
    - `CreateTunnel(Request[TunnelCreated, ConnectedToVPN | DNSConfigured])` with `names_of_ports_to_forward`, `backend_name`, `veth_cidr`, `ports_to_forward_from_vpeer_to_loopback`
    - `StartTunnel(Request[TunnelStopped, ConfigUsed | TunnelStarted | ConnectedToVPN | DNSConfigured | TunnelStatusUpdated | PortsRebound])` with `rebind_ports_every` support
    - `DestroyTunnel(Request[TunnelDestroyed, Never])`
    - `ListRegions(Request[RegionsListed, Never])` with optional `backend_name`
    - `ListTunnels(Request[TunnelsListed, Never])`
  - **Responses:** `ProcessTerminated`, `CommandNotFound`, `ProcessKilled`, `TunnelCreated`, `TunnelDestroyed`, `TunnelStopped`, `RegionsListed`, `TunnelsListed`
  - **Events:** `ProcessStarted`, `ProcessRestarted`, `ConnectedToVPN`, `DNSConfigured`, `ConfigUsed`, `TunnelStarted`, `TunnelStatusUpdated`, `PortsRebound`
  - **Data models:** `TunnelInfo` (name, vpn_connected, region_id, public_ip, gateway_ip, tun_ip, forwarded_ports, veth, veth_ip, vpeer, vpeer_ip, processes), `ProcessInfo` (pid, command, args), `Country`, `BackendInfo`, `TunnelName = str`, `RequestID = str`
  - `CODEC` for serialization (covers all request, response, and event types)

### Server Package (app/packages/server)

- `service.py` — `Service` class: holds `exit_stacks`, `namespaces`, `tunnel_contexts`, `processes` dicts keyed by `TunnelName`. Handlers: `handle_run_process`, `handle_kill_process`, `handle_create_tunnel`, `handle_start_tunnel`, `handle_destroy_tunnel`, `handle_list_regions`, `handle_list_tunnels`. Also defines `BackendConfig` dataclass for loading backend configs from YAML files.
- `server.py` — `Server` class: `Server.listen(config, *, on_tunnels_changed)` creates a `Service` and wires all handlers via `IPCServer.listen()`; `wait_forever()` blocks indefinitely. Enforces root via `_ensure_running_as_root()`.
- `config.py` — `ServerConfig` dataclass: `socket_file_path`, `namespace_base_folder_path`, `backends_folder_path`, `default_backend_name`. `ServerConfig.load(folder_path)` reads from `{folder}/server.yaml`.
- `netns.py` — `Namespace.create(name, *, base_folder_path)` async context manager: uses `unshare --net --mount` to create isolated namespaces (persistent via `tail -f /dev/null`); PID stored in `{base_folder_path}/{name}/pid`. `enter()` calls `setns()` via `/proc/{pid}/ns/{mnt,net}` — safe as `preexec_fn`. `directory` property returns `{base_folder_path}/{name}/`.
- `network_interfaces.py` — `NetworkInterfaces.add(netns)` creates a veth pair (host: `vpt{slot}v`, netns: `vpt{slot}p`) with `10.200.{slot}.x/24` addresses and a default route, moves the peer into the netns via `ip link set … netns {pid}`. Exposes `veth`, `vpeer`, `veth_ip`, `vpeer_ip`.
- `dns.py` — `DNS.setup(netns)` writes an initial `resolv.conf` to `netns.directory / "resolv.conf"` and bind-mounts it into `/etc/resolv.conf` inside the netns. Also writes `nsswitch.conf` with `hosts: files dns` (stripping `resolve`/`mdns`/`myhostname`) and bind-mounts it into `/etc/nsswitch.conf`. The bind-mounted `resolv.conf` is updated in-place by `openvpn_connected()` when VPN connects.
- `dns_leak_guard.py` — `DnsLeakGuard.activate(netns, ni)` async context manager: loads nftables rules **inside the netns** that drop outgoing UDP/TCP port 53 on the vpeer interface.
- `internet.py` — `Internet.share(name, ni)` enables IP forwarding, applies `internet.nft` rules (masquerade for the netns subnet, explicit forward accepts for the veth interface).
- `_run.py` — `async run(command, check, preexec_fn) -> int`: subprocess helper that logs both stdout and stderr via loguru (no capture).
- `handlers/` — WIP directory for splitting `service.py` into separate files. Only `list_regions.py` is implemented; `create_tunnel.py` and `kill_process.py` are empty stubs.

### Client Package (app/packages/client)

- `client.py` — `Client` class: `Client.connect(config)` async context manager (accepts `ClientConfig` or `Path`); `run_process()` sends `RunProcess` and returns exit code (127 for `CommandNotFound`); `kill_process(pid, signal)` sends `KillProcess`; `create_tunnel()` sends `CreateTunnel` and returns `TunnelCreated`; `start_tunnel()` sends `StartTunnel` with callbacks for `ConfigUsed`, `TunnelStatusUpdated`, `PortsRebound` events; `destroy_tunnel()` sends `DestroyTunnel`; `list_regions()` sends `ListRegions` with optional `backend_name`; `list_tunnels()` sends `ListTunnels`; `lookup_tunnel()` looks up a tunnel by name from `list_tunnels()`.
- `config.py` — `ClientConfig` (pydantic model): `socket_file_path`. `ClientConfig.load(folder_path)` reads from `{folder}/client.yaml`. `TunnelConfig` (pydantic model): `name`, `region_id`, `names_of_ports_to_forward`, `backend_name`, `veth_cidr`, `rebind_ports_every`, `ports_to_forward_from_vpeer_to_loopback`. `TunnelConfig.load_all(folder_path)` reads all YAML files from `{folder}/tunnels/`.

### VPN Package (app/packages/vpn)

- `__init__.py` — Backend abstraction: `Backend` protocol with `connect()` context manager (yields `Session`) and `list_regions()`. `Session` dataclass with `gateway_ip`, `tun_ip`, `dns_servers`, `forward_port` (context manager returning port number). `Region` dataclass. `get_backend(name)` and `list_backends()` use `vpn_passthrough.vpn_backends` entry points for discovery.

### PIA Package (app/packages/pia)

Standalone utility for connecting a named netns to PIA VPN. All internal modules are prefixed with `_` (private); only the public API in `__init__.py` is exported.

- `_models.py` — Plain dataclasses and `NewType` aliases: `Auth`, `RegionID`, `Region`, `Payload`, `Signature`, `PayloadAndSignature`, `ForwardedPort`.
- `_run.py` — `async run(command, *, check, preexec_fn) -> (returncode, stdout_bytes)`: subprocess helper.
- `_server_list.py` — `fetch_server(region_id)` and `fetch_regions()`.
- `_credentials.py` — `credentials_file(auth)` async context manager for OpenVPN credentials.
- `_openvpn.py` — `openvpn_connected()` async context manager: runs OpenVPN inside netns, yields `(gateway_ip, tun_ip, dns_servers)`.
- `_gateway.py` — `allocate_forwarded_port()` and `rebind_loop()` for PIA port forwarding.
- `ca.rsa.4096.crt` — PIA RSA 4096 CA certificate.
- `__init__.py` — `PIA` frozen dataclass with `connect()` method, module-level `connect()` function, `PIASession` with `gateway_ip`, `tun_ip`, `dns_servers`, `forwarded_ports`.

### App Package (app/packages/app)

- `cli.py` — Click CLI. Global `app` group option: `--config FOLDER` (env: `VPN_PASSTHROUGH_CONFIG`). Config folder path stored as `ctx.obj.config_folder_path`. Commands access it via `pass_config_folder` decorator.
- `commands/start_server.py` — Loads `ServerConfig`, starts `Server.listen()`, sends `sd_notify("READY=1")`.
- `commands/start_tunnel.py` — Loads `ClientConfig` and `TunnelConfig`, sends `StartTunnel`; sends `sd_notify` for systemd readiness and status updates. Suitable for use as a systemd service.
- `commands/create_tunnel.py` — Loads `ClientConfig` and `TunnelConfig`, sends `CreateTunnel`, blocks until SIGINT/SIGTERM then destroys.
- `commands/destroy_tunnel.py` — Sends `DestroyTunnel`.
- `commands/run_process.py` — Sends `RunProcess` with dup'd stdin/stdout/stderr fds; SIGINT/SIGTERM forwarded via `kill_process()`. Supports `--in-tunnel`, `--region-id`, `--backend-name`, `--configure-with`.
- `commands/debug_tunnel.py` — Opens a PTY, runs bash inside a tunnel with raw terminal mode and SIGWINCH forwarding.
- `commands/list_tunnels.py` — Sends `ListTunnels`; table or JSON output. `--with-processes` adds process info.
- `commands/list_regions.py` — Sends `ListRegions` with optional `--backend-name`; table or JSON output.
- `commands/list_backends.py` — Lists configured backends and available backend types.
- `commands/show_config.py` — Prints loaded config as YAML. `--empty` prints defaults. `--server-only` / `--client-only` for partial output.
- `commands/_helpers.py` — `pass_config_folder` decorator; `lookup_or_create_tunnel()` context manager for temp tunnels.
