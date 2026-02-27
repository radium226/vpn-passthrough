# Tunnel name not validated before use in netns.py

**File**: `packages/server/src/radium226/vpn_passthrough/server/netns.py`
**Priority**: High

## Problem

The tunnel name is used directly in:
- `hashlib.md5(name.encode()).hexdigest()[:4]` — to derive a slot/subnet
- Shell commands passed to `unshare` / `ip`
- Filesystem paths under `./namespaces/{name}/`

There is no length check or character whitelist. A very long name or one
containing path separators (`/`) or shell metacharacters could:
- Create unexpected directory structures (path traversal via `namespaces/../../...`)
- Break `ip netns` commands if the name is passed unsanitised

## Fix

Validate the tunnel name before any use:

```python
import re
_TUNNEL_NAME_RE = re.compile(r'^[a-zA-Z0-9_-]{1,64}$')

if not _TUNNEL_NAME_RE.match(name):
    raise ValueError(f"Invalid tunnel name: {name!r}")
```
