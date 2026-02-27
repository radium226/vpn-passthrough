# Hardcoded capability list in linux.py

**File**: `packages/server/src/radium226/vpn_passthrough/server/linux.py`
**Priority**: Low

## Problem

The capability set granted to spawned processes is hardcoded in `linux.py`
(lines ~17-32). The comment says these are "Docker/Podman container
capabilities" but there is no explanation of which capabilities are needed for
which use case, and no way to configure a different set per tunnel or per
process.

## Fix

Document which capabilities are required and why (e.g. `CAP_NET_RAW` for
`ping`, `CAP_NET_BIND_SERVICE` for binding low ports). Consider making the
capability list a parameter of `make_preexec_fn()` so callers can request a
minimal set.
