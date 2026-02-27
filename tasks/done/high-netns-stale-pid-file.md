# Stale PID file in netns.py — unsafe setns() after crash/restart

**File**: `packages/server/src/radium226/vpn_passthrough/server/netns.py`
**Priority**: High

## Problem

`Namespace.create()` stores the namespace-holding process PID in
`./namespaces/{name}/pid`. If the server crashes and restarts:

1. The old `tail -f /dev/null` process may have died, freeing the PID.
2. The kernel may reuse that PID for an unrelated process.
3. A new `Namespace.create()` call reads the stale file and calls `setns()`
   into the wrong (or now non-existent) namespace — silently corrupting process
   isolation.

There is also no locking: two concurrent `Namespace.create()` calls for the
same name could race on PID file creation.

## Fix

- Validate the PID from the file is still the expected `tail` process before
  using it (e.g. check `/proc/{pid}/cmdline` or use a lock file).
- On server startup, detect and clean up stale namespace directories.
- Use `O_EXCL` or a file lock when creating the PID file to prevent races.
