# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

VPN passthrough — a system for executing commands through a daemon over Unix domain sockets with file descriptor passing (`SCM_RIGHTS`). The repo is a monorepo with seven packages under `packages/`.

## Monorepo Structure

- **packages/ipc** — IPC library: async Unix socket transport, generic `Request[ResponseT, EventT]` protocol with `Codec`, `Server`/`Client` classes, request correlation via `id`/`request_id`, and event multiplexing. Exports `IPCServer` and `IPCClient`.
- **packages/messages** — Protocol message types: `RunProcess`/`KillProcess`/`CreateTunnel`/`DestroyTunnel`/`ListRegions`/`ListTunnels` requests; `ProcessStarted`/`ProcessRestarted`/`ConnectedToVPN`/`DNSConfigured`/`ProcessTerminated`/`CommandNotFound`/`ProcessKilled`/`TunnelCreated`/`TunnelDestroyed`/`RegionsListed`/`TunnelsListed`/`Tunnel`/`Country`/`TunnelInfo`/`ProcessInfo` responses/events; and `CODEC` for serialization. `CreateTunnel` accepts optional PIA credentials (`region_id`, `username`, `password`) and `number_of_ports_to_forward`; emits `DNSConfigured` then `ConnectedToVPN` (with `remote_ip`, `gateway_ip`, `tun_ip`, `forwarded_ports`) when VPN connects. `ListTunnels` returns `TunnelsListed` with a list of `TunnelInfo` (name, vpn_connected, region_id, public_ip, gateway_ip, tun_ip, forwarded_ports, processes). Namespace: `radium226.vpn_passthrough.messages`.
- **packages/server** — Daemon/server logic: `Service` class with all handlers (`RunProcess`/`KillProcess`/`ListRegions`/`CreateTunnel`/`DestroyTunnel`/`ListTunnels`), netns support (`netns.py`, `network_interfaces.py`, `dns.py`, `dns_leak_guard.py`, `internet.py`). `Server` class with `Server.listen(config)` context manager and `wait_forever()`. Namespace: `radium226.vpn_passthrough.server`.
- **packages/client** — High-level client: `Client` class with `Client.connect()` context manager, `run_process()`, `kill_process()`, `create_tunnel()` (with optional PIA params), `destroy_tunnel()`, `list_regions()`, and `list_tunnels()`. Tests live here. Namespace: `radium226.vpn_passthrough.client`.
- **packages/app** — CLI application: `vpn-passthrough` binary with `start-server`, `run-process`, `create-tunnel`, `destroy-tunnel`, `list-regions`, `list-tunnels`, `debug-tunnel`, and `show-config` commands. Global options: `--socket`, `--config/-c` (extra config file), `--skip-user-config` (skip XDG user config; always applied for `start-server`). Config loaded via `Config.load().merge_with(Config(...))` and stored in `ctx.obj.config` (a `SimpleNamespace`); commands access it via the `pass_config` decorator. `Config` fields: `socket_file_path` (default `/run/vpn-passthrough/vpn-passthrough.socket`), `namespace_base_folder_path` (default `/run/vpn-passthrough/namespaces`), `vpn_user`, `vpn_password`. `create-tunnel` blocks until CTRL+C; accepts `--region-id`, `--vpn-user`, `--vpn-password`, `--without-vpn`, `--number-of-ports-to-forward`. `list-tunnels` shows active tunnels with VPN status, region, IPs, and forwarded ports; `--with-processes` adds a column of running PIDs/commands; `--format table|json` selects output format. `debug-tunnel` runs a bash shell inside a tunnel with PTY proxying and raw terminal mode. `show-config` prints the loaded config as YAML; `--empty` prints defaults instead. Depends on server and client.
- **packages/pia** — PIA VPN integration: connects a Linux network namespace to Private Internet Access via OpenVPN. Standalone (no workspace deps, only `loguru` + `httpx`). Entry point: `PIA` frozen dataclass holding config, with `PIA(...).connect()` async context manager yielding a `PIASession`. Also exposes a module-level `connect()` function. Namespace: `radium226.vpn_passthrough.pia`.
- **packages/arch** — Arch Linux packaging: `PKGBUILD` that builds all workspace packages from source tarballs (`radium226_vpn_passthrough_*.tar.gz`) using `python -m build --wheel --no-isolation` and installs with `python -m installer --destdir`. makedepends: `uv`, `python-installer`, `python-wheel`, `python-build`, `python-uv-build` (required for `--no-isolation` since the build backend is not fetched automatically). Default config generated dynamically in `package()` by running `vpn-passthrough --skip-user-config show-config --empty` with `PYTHONPATH` pointing at the freshly installed site-packages; declared in `backup=` so pacman creates `.pacnew` on upgrade. `vpn-passthrough.tmpfiles` creates `/run/vpn-passthrough` (group `vpn-passthrough`, 0750) and `/run/vpn-passthrough/namespaces` (root-only, 0750). `vpn-passthrough.install` notifies the user to merge any `.pacnew` on upgrade. Also ships `vpn-passthrough.service` (systemd unit) and `vpn-passthrough.sysusers`.

Dependency chain: `app → server, client → messages → ipc`; `server → pia`; `pia` is independent of the IPC stack

## Commands

Each package is independent — **`cd` into the package directory** before running commands.

```bash
cd packages/ipc   # or packages/messages, packages/server, packages/client, packages/app, packages/pia

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

## Architecture Details

### IPC Package (packages/ipc)

Three layers — **transport**, **protocol**, and **server/client**:

- **Transport** (`transport.py`): `Connection` class wrapping a non-blocking Unix socket with `send_frame`/`receive_frame` using `Framing` protocol (default: `NullCharFraming` with `\0` delimiter). `Frame` = bytes + fd list. `accept_connections()` and `open_connection()` for server/client socket setup.
- **Protocol** (`protocol.py`): Generic `Request[ResponseT, EventT]` base class with phantom types resolved at class creation via `__init_subclass__`. `Response` structural protocol (has `request_id`). `Codec` dataclass with `encode`/`decode`. `ResponseHandler` bundles `on_event` and `on_response` callbacks.
- **Server** (`server.py`): Generic `Server` class handling connections, decoding frames, dispatching requests to registered handlers, emitting events, and sending responses. `RequestHandler` dataclass (defined in `protocol.py`) bundles a `request_type` with an async `on_request` callback. `Server.listen()` starts the serve task and waits for the socket file to appear. Exported as `IPCServer`.
- **Client** (`client.py`): Generic `Client` class with `request()` method that sends a request, registers a `ResponseHandler`, and awaits completion. Background `_receive_loop` routes responses and events to pending handlers. `Client.connect()` is the async context manager entry point. Exported as `IPCClient`.
- **IPC** (`ipc.py`): Thin wrappers `open_server()` and `open_client()` delegating to `IPCServer.listen()` and `IPCClient.connect()`.

### Messages Package (packages/messages)

- `__init__.py` — Pydantic message types:
  - `RunProcess(Request[ProcessTerminated | CommandNotFound, ProcessStarted | ProcessRestarted])` with `restart_every`, `kill_with`, `in_tunnel`, `cwd`, `username`, `gid`, `ambient_capabilities` params; `command` and `args` support Jinja2 template variables (`public_ip`, `gateway_ip`, `tun_ip`, `forwarded_ports`) resolved from the tunnel context at spawn time
  - `KillProcess(Request[ProcessKilled, Never])`
  - `CreateTunnel(Request[TunnelCreated, ConnectedToVPN | DNSConfigured])` — create a named netns tunnel with optional PIA VPN (`region_id`, `username`, `password`, `number_of_ports_to_forward`); emits `DNSConfigured` (with `nameservers`) then `ConnectedToVPN` (with `remote_ip`, `gateway_ip`, `tun_ip`, `forwarded_ports`) when VPN connects
  - `DestroyTunnel(Request[TunnelDestroyed, Never])` — tear down a tunnel by name
  - `ListRegions(Request[RegionsListed, Never])` — list available PIA regions
  - `ListTunnels(Request[TunnelsListed, Never])` — list active tunnels; response is `TunnelsListed` containing a list of `TunnelInfo` (name, vpn_connected, region_id, public_ip, gateway_ip, tun_ip, forwarded_ports, processes); `ProcessInfo` has pid, command, args (rendered)
  - All response/event types including `TunnelCreated`, `TunnelDestroyed`, `ConnectedToVPN`, `DNSConfigured`, `RegionsListed`, `TunnelsListed`, `Country`, `TunnelInfo`, `ProcessInfo`
  - `TunnelName = str` type alias used to key tunnel state
  - `CODEC` for serialization (covers all request and response/event types)

### Server Package (packages/server)

- `service.py` — `Service` class (replaces old `daemon.py`/`TunnelRegistry`): holds `exit_stacks`, `namespaces`, `tunnel_contexts`, `pia_contexts`, and `processes` dicts keyed by `TunnelName`. `handle_run_process` resolves Jinja2 templates in `command`/`args` from tunnel context (`public_ip`, `gateway_ip`, `tun_ip`, `forwarded_ports`), then spawns subprocess with passed fds using `start_new_session=True`, emits `ProcessStarted`/`ProcessRestarted`, returns `ProcessTerminated` or `CommandNotFound`; tracks each live PID in `self.processes[tunnel_name]` (registers after spawn, removes before kill-for-restart and after natural exit). `handle_kill_process` uses `os.killpg()`. `handle_create_tunnel` builds a full netns stack stored in `AsyncExitStack`, optionally connects to PIA VPN, stores `region_id` in `_TunnelContext`, activates `DnsLeakGuard` to prevent DNS leaks over the veth, and emits `DNSConfigured` then `ConnectedToVPN` (with `tun_ip`, fetching external IP via `curl ifconfig.me` in-netns); `handle_destroy_tunnel` calls `aclose()` on the stack and clears the process map. `handle_list_regions` fetches PIA region list. `handle_list_tunnels` returns all active tunnels with their VPN context (including `region_id`) and running processes.
- `server.py` — `Server` class: `Server.listen(socket_file_path, namespace_base_folder_path)` creates a `Service` and wires all handlers via `IPCServer.listen()`; `wait_forever()` blocks indefinitely. Enforces root via `_ensure_running_as_root()`.
- `netns.py` — `Namespace.create(name, *, base_folder_path)` async context manager: uses `unshare --net --mount` to create isolated namespaces (persistent via `tail -f /dev/null`); PID stored in `{base_folder_path}/{name}/pid`. `enter()` calls `setns()` via `/proc/{pid}/ns/{mnt,net}` — safe as `preexec_fn`. `directory` property returns `{base_folder_path}/{name}/`.
- `network_interfaces.py` — `NetworkInterfaces.add(netns)` creates a veth pair (host: `vpt{slot}v`, netns: `vpt{slot}p`) with `10.200.{slot}.x/24` addresses and a default route, moves the peer into the netns via `ip link set … netns {pid}`. Exposes `veth`, `vpeer`, `veth_addr`, `vpeer_addr`.
- `dns.py` — `DNS.setup(netns)` writes an initial `resolv.conf` to `netns.directory / "resolv.conf"` and bind-mounts it into `/etc/resolv.conf` inside the netns (removes symlink first if needed). Also writes `nsswitch.conf` to `netns.directory / "nsswitch.conf"` with `hosts: files dns` (stripping `resolve`/`mdns`/`myhostname`) and bind-mounts it into `/etc/nsswitch.conf`, preventing glibc from routing lookups through systemd-resolved or mDNS. The bind-mounted `resolv.conf` is updated in-place by `openvpn_connected()` when VPN connects.
- `dns_leak_guard.py` — `DnsLeakGuard.activate(netns, ni)` async context manager: loads nftables rules **inside the netns** that drop outgoing UDP/TCP port 53 on the vpeer interface, preventing DNS queries from leaking through the veth pair to the host instead of going through the VPN tunnel. Deletes the `inet dns_leak_guard` table on cleanup.
- `internet.py` — `Internet.share(name, ni)` enables IP forwarding, applies `internet.nft` rules (masquerade for the netns subnet, explicit forward accepts for the veth interface), and injects `iifname`/`oifname` accept rules into the host's `inet filter forward` chain (tracked by handle, removed on cleanup). This last step is required because in Linux netfilter, `accept` from one table does not prevent subsequent tables from dropping the packet.
- `_run.py` — `async run(command, check, preexec_fn) -> int`: subprocess helper that logs both stdout and stderr via loguru (no capture).
- `handlers/` — WIP directory for splitting `service.py` into separate files. Only `list_regions.py` has content (with a `handle()` async function); `create_tunnel.py` and `kill_process.py` are empty stubs — their logic still lives in `service.py`.

### Client Package (packages/client)

- `client.py` — `Client` class: `Client.connect(socket_file_path)` async context manager; `run_process(command, args, *, fds, restart_every, kill_with, in_tunnel, cwd, username, gid, on_pid_received)` sends `RunProcess` and returns the exit code (127 for `CommandNotFound`); `kill_process(pid, signal)` sends `KillProcess`; `create_tunnel(name, *, region_id, username, password, number_of_ports_to_forward)` sends `CreateTunnel`, logs `DNSConfigured` and `ConnectedToVPN` events, and returns `TunnelCreated`; `destroy_tunnel(name)` sends `DestroyTunnel` and awaits `TunnelDestroyed`; `list_regions()` sends `ListRegions` and returns a list of `Country`; `list_tunnels()` sends `ListTunnels` and returns a list of `TunnelInfo` (always includes running processes).
- `exec.py` — Lower-level exec function (legacy, used as reference).
- `tests/test_exec.py` — Integration tests for the daemon/exec interaction.

### PIA Package (packages/pia)

Standalone utility for connecting a named netns to PIA VPN. All internal modules are prefixed with `_` (private); only the public API in `__init__.py` is exported.

- `_models.py` — Plain dataclasses and `NewType` aliases: `Auth` (user + password), `RegionID`, `Region`, `Payload`, `Signature`, `PayloadAndSignature`, `ForwardedPort` (number + payload/signature for rebinding).
- `_run.py` — `async run(command, *, check, preexec_fn) -> (returncode, stdout_bytes)`: subprocess helper that captures stdout and logs stderr via loguru.
- `_server_list.py` — `fetch_server(region_id) -> (ip, port)`: fetches PIA serverlist API, parses the JSON prefix. `fetch_regions() -> list[Region]`: returns all available PIA regions.
- `_credentials.py` — `credentials_file(auth)` async context manager: writes a two-line OpenVPN credentials file to a temp path (`chmod 600`) and removes it on exit.
- `_openvpn.py` — `openvpn_connected(netns_name, server_ip, server_port, credentials_path, *, enter_netns, resolv_conf_path, ca_cert_path)` async context manager: uses `enter_netns` callable as `preexec_fn`, runs `openvpn` with a temp `--up` script that pipes `$route_vpn_gateway`, `$ifconfig_local` (tun IP), then DNS IPs to Python. Yields `(gateway_ip, tun_ip, dns_servers)`, writes `resolv_conf_path` with nameservers, and restores it on exit.
- `ca.rsa.4096.crt` — PIA RSA 4096 CA certificate bundled from `pia-foss/manual-connections` GitHub repo. Used as default `ca_cert_path`.
- `_gateway.py` — `allocate_forwarded_port(gateway_ip, auth, enter_netns) -> ForwardedPort`: gets a PIA auth token, fetches port signature from in-netns gateway via `curl --insecure` (using `enter_netns`), decodes base64 payload, performs initial bind. `rebind_loop(gateway_ip, forwarded_port, enter_netns, interval)`: background coroutine that rebinds every 30 s.
- `__init__.py` — `PIA` frozen dataclass; `PIA.connect()` delegates to module-level `connect()`. `connect(netns_name, auth, region_id, *, enter_netns, resolv_conf_path, ca_cert_path, forwarded_port_count, rebind_interval) -> PIASession`: orchestrates server list fetch → credentials file → OpenVPN → port allocation → rebind tasks. `PIASession` exposes `gateway_ip`, `tun_ip`, `dns_servers`, and `forwarded_ports`. Also exports `fetch_regions` and `Region`.
