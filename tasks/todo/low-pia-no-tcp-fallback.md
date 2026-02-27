# No TCP fallback when PIA region has no UDP servers

**File**: `packages/pia/src/radium226/vpn_passthrough/pia/_server_list.py`
**Priority**: Low

## Problem

`fetch_server(region_id)` raises `ValueError` if a region has no OpenVPN UDP
servers. There is no fallback to TCP servers, which PIA also supports.

Some networks block UDP/1194 (corporate firewalls, some ISPs), so a TCP
fallback on port 443 or 80 would significantly improve reliability.

## Fix

Try UDP first, fall back to TCP if no UDP servers are available for the
region:

```python
udp_servers = region.get("ovpnudp", {}).get("ip", [])
tcp_servers = region.get("ovpntcp", {}).get("ip", [])
if udp_servers:
    return random.choice(udp_servers), 1194
elif tcp_servers:
    return random.choice(tcp_servers), 443
else:
    raise ValueError(f"No OpenVPN servers for region {region_id}")
```

This also requires passing the protocol to `openvpn_connected()` so it can
set `--proto tcp-client` when needed.
