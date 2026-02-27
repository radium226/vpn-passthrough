# Two incompatible _run.py modules with the same name

**Files**:
- `packages/server/src/radium226/vpn_passthrough/server/_run.py` → returns `int`
- `packages/pia/src/radium226/vpn_passthrough/pia/_run.py` → returns `tuple[int, bytes]`
**Priority**: Medium

## Problem

Both modules are named `_run.py` and export `async def run(...)` but with
different signatures and behaviour:

| | server `_run.py` | pia `_run.py` |
|---|---|---|
| Return type | `int` | `tuple[int, bytes]` |
| stdout | logged, not captured | captured and returned |
| stderr | logged | logged |

This is confusing when reading cross-package code and makes it easy to call
the wrong one.

## Fix

Rename or differentiate clearly. Options:
- Rename pia's to `_run_capture.py` or fold into a shared utility in `ipc`
  with a `capture_stdout: bool` parameter.
- Document the difference explicitly in each module's docstring.
