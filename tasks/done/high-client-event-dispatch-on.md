# O(n) event dispatch and handler lookup in client/server

**Files**:
- `packages/ipc/src/radium226/vpn_passthrough/ipc/client.py` (event dispatch)
- `packages/ipc/src/radium226/vpn_passthrough/ipc/server.py` (handler lookup)
**Priority**: High

## Problem

**Client** (`client.py`): The `_receive_loop` iterates over *all* pending
requests for each received message to find a matching event type. This is O(n)
per message with n concurrent requests outstanding.

**Server** (`server.py`): Handler lookup uses `next()` over a generator
expression on every incoming request — also O(n) over the handler list.

Both are fine at current scale but will degrade noticeably under load.

## Fix

**Client**: Key `_pending` by `request_id` (already the case for responses)
and separately maintain a `dict[type, list[ResponseHandler]]` for event
routing.

**Server**: Build a `dict[type[Request], RequestHandler]` at `__init__` time
from the handler list and do O(1) lookup on each incoming request type.
