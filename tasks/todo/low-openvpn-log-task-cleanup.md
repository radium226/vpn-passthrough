# OpenVPN log tasks not awaited on cleanup in _openvpn.py

**File**: `packages/pia/src/radium226/vpn_passthrough/pia/_openvpn.py`
**Priority**: Low

## Problem

In `openvpn_connected()`'s cleanup block, log tasks are cancelled but not
awaited. The tasks may still be mid-write when the process fd is closed,
causing `CancelledError` to be raised from within the logging coroutine in an
unobserved way.

## Fix

After cancelling, await with `return_exceptions=True`:

```python
for task in log_tasks:
    task.cancel()
await asyncio.gather(*log_tasks, return_exceptions=True)
```
