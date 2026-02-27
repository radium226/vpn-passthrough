# Add server-side PIA configuration

**Priority**: Medium

## Problem

PIA credentials (`username`, `password`) and `region_id` must be passed by the
client on every `CreateTunnel` request. There is no way to configure them
server-side so that clients can create tunnels without supplying credentials
each time.

## Fix

Add a PIA config section to the server configuration (see the server
configuration task) read at startup, e.g.:

```toml
[pia]
username = "p1234567"
password = "secret"
default_region_id = "france"  # optional
```

In `handle_create_tunnel`, use server-side credentials as defaults and let
per-request values override them. If neither source provides credentials, skip
VPN setup (current behaviour with `--without-vpn`).
