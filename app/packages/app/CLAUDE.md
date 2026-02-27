# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

CLI application for VPN passthrough. Provides a `vpn-passthrough` binary with eight commands:
- `start-server` — runs the IPC server, handling all request types
- `run-process` — connects to the server and asks it to execute a command, forwarding signals via `KillProcess`
- `create-tunnel NAME [--region-id] [--vpn-user] [--vpn-password]` — creates a named network namespace tunnel, optionally connecting to PIA VPN; always blocks until SIGINT/SIGTERM then automatically destroys the tunnel. If credentials are given without `--region-id`, a random region is chosen
- `destroy-tunnel NAME` — tears down a named tunnel
- `list-regions` — lists available PIA VPN regions (table or JSON output)
- `list-tunnels [--with-processes] [--format table|json]` — lists active tunnels with VPN status, region, IPs, and forwarded ports; `--with-processes` adds a column of running PIDs/commands
- `debug-tunnel` — runs a bash shell inside a tunnel with PTY proxying and raw terminal mode
- `show-config` — prints the loaded config as YAML; `--empty` prints defaults instead

Depends on `radium226-vpn-passthrough-server` and `radium226-vpn-passthrough-client`.

## Commands

- **Install deps**: `uv sync`
- **Run all checks** (ty + ruff + pytest): `mise run check`
- **Type check**: `uv run ty check`
- **Lint**: `uv run ruff check`
- **Run tests**: `uv run python -m pytest`
- **CLI entry point**: `uv run vpn-passthrough`

## Architecture

Package: `radium226.vpn_passthrough.app` (under `src/`)

- **config.py** — `Config` Pydantic model with fields `socket_file_path` (default `/run/vpn-passthrough/vpn-passthrough.socket`), `namespace_base_folder_path` (default `/run/vpn-passthrough/namespaces`), `vpn_user`, `vpn_password`. `Config.load(file_path, *, skip_user_config)` merges system config → user XDG config (unless `skip_user_config`) → optional extra file. `merge_with(other)` overrides only fields present in `other.model_fields_set`.

- **cli.py** — Click CLI. Global `app` group options: `--socket` (overrides `socket_file_path`), `--config/-c` (extra config file), `--skip-user-config` (skip XDG user config; always applied for `start-server`). Config loaded as `Config.load(...).merge_with(Config(socket_file_path=...))` and stored as `ctx.obj.config` on a `SimpleNamespace`. `pass_config` decorator injects `ctx.obj.config` as first argument to commands. Commands:
  - `start-server`: `Server.listen(socket_file_path, namespace_base_folder_path)` + `wait_forever()`
  - `run-process`: `Client.connect()` + `run_process()` with dup'd stdin/stdout/stderr fds; SIGINT/SIGTERM forwarded via `kill_process()`
  - `create-tunnel NAME [--region-id] [--vpn-user] [--vpn-password]`: `Client.connect()` + `create_tunnel()`; always blocks until SIGINT/SIGTERM, then calls `destroy_tunnel()`. Random region chosen via `list_regions()` if credentials given without `--region-id`
  - `destroy-tunnel NAME`: `Client.connect()` + `destroy_tunnel()`
  - `list-regions [--format table|json]`: `Client.connect()` + `list_regions()`; displays PIA regions as a table or JSON
  - `list-tunnels [--with-processes] [--format table|json]`: `Client.connect()` + `list_tunnels()`; displays active tunnels (name, VPN status, region, IPs, forwarded ports); `--with-processes` adds per-tunnel process list (`pid: command args`)
  - `debug-tunnel`: opens a PTY, runs bash inside a tunnel with raw terminal mode and SIGWINCH forwarding
  - `show-config [--empty]`: prints the loaded `Config` as YAML; `--empty` prints `Config()` defaults instead

## Tech Stack

- Python 3.14, uv (build + package manager), mise (task runner)
- click for CLI, loguru for logging
- pytest + pytest-asyncio for tests, ruff for linting, ty for type checking
