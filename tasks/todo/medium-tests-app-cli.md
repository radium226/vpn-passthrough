# No tests for the app CLI

**File**: `packages/app/tests/` (does not exist)
**Priority**: Medium

## Problem

`cli.py` has zero test coverage. None of the following is verified:

- `create-tunnel --without-vpn` creates a tunnel without credentials
- `list-tunnels --with-processes` formats the process column correctly
- `list-tunnels --format json` emits valid JSON
- `list-regions --format json` emits valid JSON
- Double SIGINT doesn't crash `create-tunnel` (regression test for the fixed bug)
- `run-process` exit code propagates correctly
- Env vars `VPN_PASSTHROUGH_USERNAME` / `VPN_PASSTHROUGH_PASSWORD` are picked up

## Implementation notes

Use Click's `CliRunner` for synchronous commands. For async commands that start
the server, consider a fixture that spins up a real server on a temp socket.
The `--without-vpn` path is entirely testable without root or network access.
