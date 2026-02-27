# No dedicated server package tests

**File**: `packages/server/tests/` (does not exist)
**Priority**: Medium

## Problem

All server testing goes through `packages/client/tests/test_exec.py` as
end-to-end integration tests. There are no unit or isolation tests for server
internals:

- `Service.handle_create_tunnel()` cleanup on mid-setup exception
- `Service.handle_destroy_tunnel()` with missing tunnel name
- Concurrent `handle_run_process()` calls for the same tunnel
- `handle_list_tunnels()` with no active tunnels
- `handle_kill_process()` for an already-dead PID
- Namespace PID file corruption handling
- nftables rule cleanup on `DnsLeakGuard.__aexit__` failure

## Implementation notes

Most handlers can be tested with a mocked `Namespace`, `NetworkInterfaces`,
etc. using `unittest.mock.AsyncMock`. The `Service` class itself has no
external deps in `__init__`, making it easy to instantiate in tests.
