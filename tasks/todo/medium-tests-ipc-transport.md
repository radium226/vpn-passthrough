# Missing IPC transport tests

**File**: `packages/ipc/tests/test_transport.py` (or new test files)
**Priority**: Medium

## Problem

The existing transport tests cover basic send/receive but are missing:

- **FD passing**: send a frame with `fds`, verify the receiver gets valid open
  FDs pointing to the same file/pipe.
- **Malformed frames**: send data with no null terminator (simulate a slow
  sender), send data exceeding `MAX_BUFFER_SIZE`.
- **Large frames**: frames approaching but not exceeding `MAX_BUFFER_SIZE`.
- **Concurrent sends/receives**: two coroutines sending simultaneously on the
  same `Connection` — verify no interleaving.
- **Connection drop mid-frame**: close the socket while a frame is partially
  received — verify `EOFError` is raised cleanly.
- **Reconnect**: client disconnects and reconnects — server should accept new
  connection without issue.

## Implementation notes

Use `asyncio.create_unix_server` / `socket.socketpair()` for in-process
testing without touching the filesystem.
