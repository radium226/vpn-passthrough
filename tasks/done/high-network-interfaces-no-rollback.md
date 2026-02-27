# No rollback on partial veth setup in NetworkInterfaces

**File**: `packages/server/src/radium226/vpn_passthrough/server/network_interfaces.py`
**Priority**: High

## Problem

`NetworkInterfaces.add()` runs a sequence of `ip` commands (`ip link add`,
`ip addr add`, `ip link set`, `ip route add`) each with `check=True`. If any
command fails mid-sequence the previous commands' effects are already applied:
orphaned veth interfaces remain on the host with no cleanup path.

The context manager's `__aexit__` only runs `ip link del` on the *host* veth,
which is correct on success but may also fail if the interface was never fully
created.

## Fix

Use a try/except inside the setup sequence to call the cleanup path on any
partial failure, or restructure as a proper async context manager that only
yields after all commands succeed and guarantees cleanup even if setup is
partial.
