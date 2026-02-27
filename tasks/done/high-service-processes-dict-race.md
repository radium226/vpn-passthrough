# Race condition on processes dict in handle_run_process

**File**: `packages/server/src/radium226/vpn_passthrough/server/service.py`
**Priority**: High

## Problem

Multiple concurrent `handle_run_process()` calls for the same `tunnel_name`
mutate `self.processes[tunnel_name]` (insert on spawn, pop on exit/kill) with
no synchronisation. Python's GIL prevents low-level corruption but asyncio
yields at every `await`, so two handlers can interleave:

1. Handler A reads `self.processes[tunnel_name]` (empty dict literal assigned at line ~119)
2. Handler B does the same, overwriting A's reference
3. Processes tracked by A are invisible to `handle_list_tunnels` and never
   cleaned up by `handle_destroy_tunnel`

## Fix

Use an `asyncio.Lock` per tunnel, or protect the dict mutations with a single
`asyncio.Lock` on `Service`. Since mutations are brief (no awaits inside), a
simple lock suffices:

```python
self._processes_lock = asyncio.Lock()

async with self._processes_lock:
    if tunnel_name not in self.processes:
        self.processes[tunnel_name] = {}
```
