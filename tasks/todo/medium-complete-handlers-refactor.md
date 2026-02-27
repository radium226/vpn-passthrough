# Complete the handlers/ refactor (empty stubs)

**File**: `packages/server/src/radium226/vpn_passthrough/server/handlers/`
**Priority**: Medium

## Problem

The `handlers/` directory exists as a planned refactor of `service.py` into
per-handler files, but `create_tunnel.py` and `kill_process.py` are **empty
stubs**. Only `list_regions.py` has a stub function signature (no
implementation either). All logic remains in the monolithic `service.py`.

This is misleading: it suggests the refactor is in progress when it is not,
and the empty files contribute nothing.

## Options

1. **Complete the refactor**: move each handler from `service.py` into its own
   file in `handlers/`, update `service.py` to import and delegate. This
   improves readability and testability.
2. **Delete the stubs**: remove the `handlers/` directory entirely and keep
   `service.py` monolithic until there's a concrete reason to split.

Option 1 is preferred for maintainability.
