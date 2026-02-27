# Silent firewall failure in _list_forward_chains()

**File**: `packages/server/src/radium226/vpn_passthrough/server/internet.py`
**Priority**: High

## Problem

`_list_forward_chains()` wraps the `nft -j list ruleset` JSON parse in a broad
`except Exception` that returns an empty list on any error. If nftables output
is malformed or the command fails, the function silently falls back to "no
chains" — meaning the per-interface forward rules are never injected and traffic
through the veth is silently dropped by the host firewall.

## Fix

Raise (or at minimum log as `logger.error`) the exception so the caller knows
that firewall setup failed. At minimum log the raw output before parsing so the
failure is diagnosable.

```python
try:
    data = json.loads(stdout)
except json.JSONDecodeError:
    logger.error("nft returned unparseable output: {!r}", stdout)
    raise
```
