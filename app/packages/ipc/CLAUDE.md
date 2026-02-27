# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

IPC library for VPN passthrough using Unix domain sockets. Provides async client/server communication over `AF_UNIX` sockets with support for file descriptor passing (`SCM_RIGHTS`). Uses a generic `Request[ResponseT, EventT]` protocol with `Codec`-based serialization and request correlation via `id`/`request_id`.

## Commands

- **Install deps**: `uv sync`
- **Run all checks** (ty + ruff + pytest): `mise run check`
- **Type check**: `uv run ty check`
- **Lint**: `uv run ruff check`
- **Run tests**: `uv run python -m pytest`
- **Run a single test**: `uv run python -m pytest tests/test_server_client.py::test_request_response`

## Architecture

Package: `radium226.vpn_passthrough.ipc` (under `src/`)

- **transport.py** — `Connection` class with non-blocking Unix socket I/O, `send_frame`/`receive_frame` using `Framing` protocol (default `NullCharFraming` with `\0` delimiter). `Frame` = bytes + fd list. `accept_connections()` creates the server socket with `chmod 0o777` (world-accessible). `open_connection()` for the client side.
- **protocol.py** — Generic `Request[ResponseT, EventT]` base class with phantom types. `Response` structural protocol. `Codec` dataclass with `encode`/`decode`. `ResponseHandler` for event/response callbacks.
- **server.py** — Generic `Server` class: accepts connections, decodes frames, dispatches requests to handler, emits events, sends responses. `Server.listen()` is the main async context manager — starts the `serve()` task and polls until the socket file appears. `Server.open()` is the lower-level variant (no serving). Exported as `IPCServer`.
- **client.py** — Generic `Client` class: `request()` sends request with fds and `ResponseHandler`, background receive loop routes responses/events. `Client.connect()` is the async context manager entry point. Exported as `IPCClient`.
- **ipc.py** — Thin wrappers `open_server()` and `open_client()` delegating to `IPCServer.listen()` and `IPCClient.connect()`.

## Tech Stack

- Python 3.14, uv (build + package manager), mise (task runner)
- pydantic for message serialization, click for CLI, loguru for logging
- pytest + pytest-asyncio for tests, ruff for linting, ty for type checking
