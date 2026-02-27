# Namespace cleanup rmdir() failures silently swallowed

**File**: `packages/server/src/radium226/vpn_passthrough/server/netns.py`
**Priority**: Low

## Problem

In `Namespace.create()`'s cleanup path, `rmdir()` failures are caught with a
bare `except: pass` (or similar). If namespace directories are not cleaned up
(e.g. due to files left inside), the failure is invisible — stale directories
accumulate under `./namespaces/` and may interfere with future tunnel creation
using the same name.

## Fix

At minimum log a warning:

```python
try:
    netns.directory.rmdir()
except OSError as e:
    logger.warning("Could not remove namespace dir {}: {}", netns.directory, e)
```

Optionally use `shutil.rmtree()` for more aggressive cleanup, but only after
confirming the directory is safe to remove entirely.
