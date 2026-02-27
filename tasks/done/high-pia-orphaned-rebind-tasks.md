# Orphaned asyncio tasks when port rebind task created before tracking

**File**: `packages/server/src/radium226/vpn_passthrough/server/service.py`
**Priority**: High

## Problem

In `handle_run_process`, when `rebind_timer` fires:

```python
new_rebind_task = asyncio.create_task(rebind_loop(...))
pia_ctx.extra_rebind_tasks.append(new_rebind_task)
```

If any exception occurs between `create_task()` and `append()` (e.g. inside
`allocate_forwarded_port()`), the task is already scheduled but never tracked
in `extra_rebind_tasks` — so `handle_destroy_tunnel` will never cancel it.
The task runs forever in the background until the process exits.

## Fix

Assign to a local variable, do the async work, then track only on success:

```python
new_port = await allocate_forwarded_port(...)
new_rebind_task = asyncio.create_task(rebind_loop(...))
pia_ctx.extra_rebind_tasks.append(new_rebind_task)  # only reached if no exception above
```

This is already the current order — but the task creation itself should be
inside a try/except so that allocation failures cancel any partially-created
state.
