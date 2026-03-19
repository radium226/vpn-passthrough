# VPN Passthrough

> [!IMPORTANT]
> If you're watching this page from [the repo in GitHub](https://github.com/radium226/vpn-passthrough), please note it's only a read-only mirror from [the repo in SourceHut](https://git.sr.ht/~radium226/vpn-passthrough).
> You can follow the tickets in [this tracker](https://todo.sr.ht/~radium226/vpn-passthrough).

A daemon-based system for executing commands inside isolated Linux network namespaces with optional VPN connectivity via Private Internet Access (PIA). Processes run in complete network isolation, with DNS leak prevention enforced at the kernel level.

## Overview

`vpn-passthrough` solves the problem of running arbitrary processes through a VPN tunnel without affecting the host network. Each tunnel is an independent Linux network namespace connected to the host via a veth pair. When a VPN backend is configured, the daemon establishes a VPN connection inside the namespace, configures DNS, and optionally allocates forwarded ports — all transparently from the process's perspective.

Communication between the CLI and the daemon occurs over a Unix domain socket using a typed, correlated request/response/event protocol.

## How It Works

```
CLI (vpn-passthrough)
  └─► IPC Client ──[Unix socket]──► IPC Server
                                       └─► Service
                                             ├─ Network namespace (netns + veth)
                                             ├─ DNS leak guard (nftables)
                                             ├─ VPN connection (pluggable backend)
                                             └─ Process management (fd passing)
```

1. The daemon (`start-server`) listens on a Unix socket and manages named tunnels.
2. A tunnel is a Linux network namespace with a veth pair, a dedicated `resolv.conf`, and nftables rules that block DNS queries on the veth interface (preventing leaks to the host resolver).
3. When a VPN backend is configured, a VPN connection is launched inside the namespace; once connected, the daemon emits `ConnectedToVPN` with the assigned IPs and forwarded ports.
4. Processes run inside tunnels via `SCM_RIGHTS` file descriptor passing so that the process inherits the client's stdin/stdout/stderr over the socket boundary.
5. Command and argument templates support Jinja2 variables (`public_ip`, `gateway_ip`, `tun_ip`, `forwarded_ports`) resolved from the tunnel context at spawn time.

## Installation

### Arch Linux

```bash
cd packages/arch
makepkg -si
```

The package installs the `vpn-passthrough` binary, systemd service units, `sysusers.d` and `tmpfiles.d` fragments, and default configuration files at `/etc/vpn-passthrough/`.

### From Source

```bash
cd app/packages/app
uv sync
uv run vpn-passthrough --help
```

**Runtime dependencies:** `openvpn`, `iproute2`, `nftables`, `curl`

## Configuration

Configuration is folder-based. The default config folder is `/etc/vpn-passthrough` and contains:

| File | Purpose |
|------|---------|
| `server.yaml` | Server settings (socket path, namespace folder, backends folder, default backend) |
| `client.yaml` | Client settings (socket path) |
| `tunnels/*.yaml` | Per-tunnel configs (region, ports to forward, backend, veth CIDR, etc.) |

Override the config folder with `--config FOLDER` or the `VPN_PASSTHROUGH_CONFIG` environment variable.

**Server config fields:**

```yaml
socket_file_path: /run/vpn-passthrough/ipc.socket
namespace_base_folder_path: /run/vpn-passthrough/namespaces
backends_folder_path: /etc/vpn-passthrough/backends
default_backend_name: null
```

**Client config fields:**

```yaml
socket_file_path: /run/vpn-passthrough/ipc.socket
```

**Tunnel config fields** (in `tunnels/<name>.yaml`):

```yaml
region_id: null
names_of_ports_to_forward: []
backend_name: null
veth_cidr: null
rebind_ports_every: null
ports_to_forward_from_vpeer_to_loopback: []
```

Print the current effective configuration:

```bash
vpn-passthrough show-config
vpn-passthrough show-config --empty          # print defaults
vpn-passthrough show-config --server-only    # server section only
vpn-passthrough show-config --client-only    # client section only
```

## Usage

### Starting the Daemon

The daemon must run as root.

```bash
# Directly
sudo vpn-passthrough start-server

# Via systemd
sudo systemctl enable --now vpn-passthrough.service
```

### Global Options

```
--config FOLDER    Config folder path (env: VPN_PASSTHROUGH_CONFIG)
```

---

### `start-tunnel NAME`

Starts a tunnel and keeps it running. Sends `READY=1` to systemd when connected. Suitable for use as a systemd service. Tunnel config is loaded from `tunnels/<name>.yaml` in the config folder; CLI flags override config file values.

```bash
vpn-passthrough start-tunnel --region-id nl-amsterdam my-tunnel
vpn-passthrough start-tunnel my-tunnel   # uses config from tunnels/my-tunnel.yaml
```

A per-tunnel systemd service template is provided:

```bash
# Reads config from /etc/vpn-passthrough/tunnels/my-tunnel.yaml
sudo systemctl enable --now vpn-passthrough@my-tunnel.service
```

| Option | Description |
|--------|-------------|
| `--region-id REGION` | VPN region ID (env: `VPN_PASSTHROUGH_REGION_ID`) |
| `--backend-name NAME` | Backend name (env: `VPN_PASSTHROUGH_BACKEND`) |
| `--forward-port-for NAME` | Forward a port with the given name (repeatable) |
| `--rebind-ports-every SECONDS` | Reallocate forwarded ports every N seconds |
| `--veth-cidr CIDR` | Fixed CIDR for the veth pair (e.g. `10.200.5.0/24`) |
| `--forward-vpeer-port-to-loopback PORT` | DNAT this port on the vpeer to 127.0.0.1 inside the tunnel (repeatable) |

---

### `create-tunnel NAME`

Creates a named tunnel that persists until `CTRL+C`, then destroys it automatically.

```bash
vpn-passthrough create-tunnel my-tunnel
vpn-passthrough create-tunnel --region-id us-texas --forward-port-for transmission my-tunnel
```

| Option | Description |
|--------|-------------|
| `--region-id REGION` | VPN region ID (env: `VPN_PASSTHROUGH_REGION_ID`) |
| `--backend-name NAME` | Backend name (env: `VPN_PASSTHROUGH_BACKEND`) |
| `--forward-port-for NAME` | Forward a port with the given name (repeatable) |
| `--veth-cidr CIDR` | Fixed CIDR for the veth pair |
| `--forward-vpeer-port-to-loopback PORT` | DNAT this port on the vpeer to 127.0.0.1 (repeatable) |

---

### `destroy-tunnel NAME`

Tears down a named tunnel immediately.

```bash
vpn-passthrough destroy-tunnel my-tunnel
```

---

### `run-process [OPTIONS] COMMAND [ARGS...]`

Executes a command inside a tunnel. The process inherits the client's stdin/stdout/stderr and signals are forwarded transparently.

```bash
vpn-passthrough run-process --in-tunnel my-tunnel curl https://ifconfig.me
vpn-passthrough run-process --region-id us-texas curl https://ifconfig.me
```

| Option | Description |
|--------|-------------|
| `--in-tunnel NAME` | Use an existing named tunnel |
| `--region-id REGION` | VPN region for a temporary tunnel |
| `--backend-name NAME` | Backend name for the temporary tunnel |
| `--kill-with SIGNAL` | Signal used for restart (default: `SIGTERM`) |
| `--configure-with SCRIPT` | Script to run after port rebind and before process restart |

If `--in-tunnel` is omitted, a temporary tunnel is created for the duration of the command.

---

### `debug-tunnel [OPTIONS]`

Opens an interactive bash shell inside a tunnel with full PTY proxying (including terminal resize).

```bash
vpn-passthrough debug-tunnel --in-tunnel my-tunnel
vpn-passthrough debug-tunnel --region-id us-texas
```

---

### `list-tunnels`

Lists all active tunnels.

```bash
vpn-passthrough list-tunnels
vpn-passthrough list-tunnels --with-processes
vpn-passthrough list-tunnels --format json
```

Output columns: Name, VPN, Region, Public IP, Gateway IP, Tun IP, Forwarded Ports, (Processes)

---

### `list-regions`

Lists available VPN regions.

```bash
vpn-passthrough list-regions
vpn-passthrough list-regions --backend-name pia
vpn-passthrough list-regions --format json
```

---

### `list-backends`

Lists configured backends and available backend types.

```bash
vpn-passthrough list-backends
```

---

### `show-config`

Prints the loaded configuration as YAML.

```bash
vpn-passthrough show-config
vpn-passthrough show-config --empty
vpn-passthrough show-config --server-only
vpn-passthrough show-config --client-only
```

---

## Security Considerations

- The daemon must run as root (network namespace and nftables manipulation require `CAP_NET_ADMIN` and `CAP_SYS_ADMIN`).
- The Unix socket is owned by the `vpn-passthrough` group (mode `0660`). Add trusted users to this group to grant access.
- DNS leak prevention is enforced via nftables rules inside each namespace that drop outgoing DNS traffic on the veth interface, ensuring all DNS queries route through the VPN tunnel.
