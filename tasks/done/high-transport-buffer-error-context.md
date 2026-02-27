# BufferError in transport.py gives no size context

**File**: `packages/ipc/src/radium226/vpn_passthrough/ipc/transport.py`
**Priority**: High

## Problem

When the receive buffer exceeds `MAX_BUFFER_SIZE`, the error message is:

```
BufferError: Receive buffer exceeded 16777216 bytes
```

It doesn't report how large the buffer actually grew, making it impossible to
know whether the client sent a slightly oversized frame or is clearly
misbehaving.

## Fix

Include the actual buffer size in the message:

```python
raise BufferError(
    f"Receive buffer exceeded limit: {len(self._buffer)} > {MAX_BUFFER_SIZE} bytes"
)
```
