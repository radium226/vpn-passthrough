# Missing or imprecise type annotations

**Files**: various
**Priority**: Medium

## Issues

### `protocol.py` — implicit `None` returns

`validate_response()` and `validate_event()` return `None` implicitly in some
branches. Add explicit `-> None` return type annotations.

### `client.py` — complex `_pending` dict type

`self._pending` has a complex tuple value type. Extract a named type alias:

```python
from typing import TypeAlias
_PendingEntry: TypeAlias = tuple[ResponseHandler[Any, Any], asyncio.Future[Any]]
_pending: dict[str, _PendingEntry]
```

### `service.py` — double `ctx` check

The pattern `if ctx is not None: ... ctx.x ...` appears twice in the rebind
block (lines ~185-192) even though `ctx` cannot change between the two checks
in a single-threaded async context. Restructure to check once and use `ctx`
confidently inside the block.

### General

Run `uv run ty check` after fixes to confirm no new issues are introduced.
