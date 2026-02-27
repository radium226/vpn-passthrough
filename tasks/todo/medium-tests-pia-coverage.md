# Thin test coverage for the PIA package

**File**: `packages/pia/tests/`
**Priority**: Medium

## Problem

Only `_decode_port()` (a pure function) is tested. Everything else is
untested:

- `fetch_server()` and `fetch_regions()` — HTTP calls to PIA API (can be
  mocked with `httpx` test transport)
- `credentials_file()` — file creation, permissions, cleanup on exception
- `openvpn_connected()` — subprocess lifecycle, DNS server extraction from
  `--up` script pipe
- `allocate_forwarded_port()` — token fetch, port signature decode, initial bind
- `rebind_loop()` — periodic rebind, exception handling, cancellation

## Implementation notes

Use `httpx.MockTransport` to intercept HTTP calls. Use `unittest.mock.patch`
or `asyncio.subprocess` mocking for OpenVPN. `credentials_file()` can be
tested directly — verify `os.stat().st_mode` and that content is correct.
