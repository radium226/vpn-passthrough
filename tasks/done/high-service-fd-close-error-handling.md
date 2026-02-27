# os.close() on FDs without error handling in service.py

**File**: `packages/server/src/radium226/vpn_passthrough/server/service.py`
**Priority**: High

## Problem

After a process exits, `handle_run_process()` closes the three stdio FDs with
bare `os.close()` calls (lines ~209-211). If an FD is already invalid (e.g.
the client disconnected and the server side already closed it), `os.close()`
raises `OSError: [Errno 9] Bad file descriptor`, which propagates uncaught and
corrupts the handler's return path.

The same issue exists in the `FileNotFoundError` path (lines ~143-145).

## Fix

Wrap each `os.close()` in a try/except and log the error:

```python
for fd in (stdin_fd, stdout_fd, stderr_fd):
    try:
        os.close(fd)
    except OSError as e:
        logger.warning("Failed to close fd {}: {}", fd, e)
```
