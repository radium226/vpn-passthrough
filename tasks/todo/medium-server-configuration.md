# Add server configuration (paths, runtime dirs)

**Priority**: Medium

## Problem

Several paths are hardcoded throughout the server:

- `./namespaces/{name}/` — netns working directory (`netns.py`)
- Socket file path passed ad-hoc via `ServerConfig(socket_file_path=...)`
- No standard location for per-netns `resolv.conf`, `nsswitch.conf`, pid files

This makes the daemon unsuitable for system-level deployment (e.g. as a
systemd service writing to `/var/run/`).

## Fix

Extend `ServerConfig` to hold all configurable paths and read them from a TOML
config file (e.g. `/etc/vpn-passthrough/config.toml`) with sensible defaults:

```toml
[server]
socket_path = "/var/run/vpn-passthrough/daemon.sock"
namespaces_dir = "/var/run/vpn-passthrough/namespaces"
```

Pass `ServerConfig` down to `Namespace.create()`, `DNS.setup()`, and
`NetworkInterfaces.add()` so they all derive their paths from config instead of
using relative or hardcoded paths. The CLI `start-server` command should accept
a `--config` option pointing to the config file.
