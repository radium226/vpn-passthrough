# VPN Passthrough

> [!IMPORTANT]
> If you're watching this page from [the repo in GitHub](https://github.com/radium226/vpn-passthrough), please note it's only a read-only mirror from [the repo in SourceHut](https://git.sr.ht/~radium226/vpn-passthrough). 
> You can follow the tickets in [this tracker](https://todo.sr.ht/~radium226/vpn-passthrough).

A daemon-based system for executing commands inside isolated Linux network namespaces with optional VPN connectivity via Private Internet Access (PIA). Processes run in complete network isolation, with DNS leak prevention enforced at the kernel level.

## Overview

`vpn-passthrough` solves the problem of running arbitrary processes through a VPN tunnel without affecting the host network. Each tunnel is an independent Linux network namespace connected to the host via a veth pair. When a PIA region is specified, the daemon establishes an OpenVPN connection inside the namespace, configures DNS, and optionally allocates forwarded ports — all transparently from the process's perspective.

Communication between the CLI and the daemon occurs over a Unix domain socket using a typed, correlated request/response/event protocol.

## How It Works

```
CLI (vpn-passthrough)
  └─► IPC Client ──[Unix socket]──► IPC Server
                                       └─► Service
                                             ├─ Network namespace (netns + veth)
                                             ├─ DNS leak guard (nftables)
                                             ├─ VPN connection (OpenVPN + PIA)
                                             └─ Process management (fd passing)
```

1. The daemon (`start-server`) listens on a Unix socket and manages named tunnels.
2. A tunnel is a Linux network namespace with a veth pair, a dedicated `resolv.conf`, and nftables rules that block DNS queries on the veth interface (preventing leaks to the host resolver).
3. When a PIA region is provided, OpenVPN is launched inside the namespace; once connected, the daemon emits `ConnectedToVPN` with the assigned IPs and forwarded ports.
4. Processes run inside tunnels via `SCM_RIGHTS` file descriptor passing so that the process inherits the client's stdin/stdout/stderr over the socket boundary.
5. Command and argument templates support Jinja2 variables (`public_ip`, `gateway_ip`, `tun_ip`, `forwarded_ports`) resolved from the tunnel context at spawn time.

## Installation

### Arch Linux

```bash
cd packages/arch
makepkg -si
```

The package installs the `vpn-passthrough` binary, a systemd service and socket unit, `sysusers.d` and `tmpfiles.d` fragments, and a default configuration at `/etc/vpn-passthrough/config.yaml`.

### From Source

```bash
cd packages/app
uv sync
uv run vpn-passthrough --help
```

**Runtime dependencies:** `openvpn`, `iproute2`, `nftables`, `curl`

## Configuration

Configuration is merged from the following sources in order (later values override earlier ones):

| Source | Path |
|--------|------|
| System config | `/etc/vpn-passthrough/config.yaml` |
| User config | `~/.config/vpn-passthrough/config.yaml` |
| CLI flag | `--config FILE` |

**Available fields:**

```yaml
socket_file_path: /run/vpn-passthrough/ipc.socket
namespace_base_folder_path: /run/vpn-passthrough/namespaces
vpn_user: null
vpn_password: null
region_id: null
number_of_ports_to_forward: 0
port_rebind_every: 604800.0   # seconds (default: 1 week)
```

Print the current effective configuration:

```bash
vpn-passthrough show-config
vpn-passthrough show-config --empty   # print defaults
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
--socket PATH        Unix socket path (env: VPN_PASSTHROUGH_SOCKET)
--config, -c FILE    Extra config file to merge
--skip-user-config   Skip the XDG user config file
```

---

### `create-tunnel NAME`

Creates a named tunnel that persists until `CTRL+C`, then destroys it automatically.

```bash
vpn-passthrough create-tunnel my-tunnel
vpn-passthrough create-tunnel --region-id us-texas --number-of-ports-to-forward 2 my-tunnel
vpn-passthrough create-tunnel --without-vpn my-tunnel
```

| Option | Description |
|--------|-------------|
| `--region-id REGION` | PIA region ID |
| `--vpn-user USERNAME` | PIA username (env: `VPN_PASSTHROUGH_USERNAME`) |
| `--vpn-password PASSWORD` | PIA password (env: `VPN_PASSTHROUGH_PASSWORD`) |
| `--without-vpn` | Create namespace without a VPN connection |
| `--number-of-ports-to-forward N` | Number of ports to forward (env: `VPN_PASSTHROUGH_NUMBER_OF_PORTS_TO_FORWARD`) |

---

### `start-tunnel NAME`

Starts a tunnel and keeps it running. Sends `READY=1` to systemd when connected. Suitable for use as a systemd service.

```bash
vpn-passthrough start-tunnel --region-id nl-amsterdam my-tunnel
vpn-passthrough start-tunnel --persistent my-tunnel   # writes config to /etc/vpn-passthrough/tunnels/
```

A per-tunnel systemd service template is provided:

```bash
# Reads config from /etc/vpn-passthrough/tunnels/my-tunnel.yaml
sudo systemctl enable --now vpn-passthrough@my-tunnel.service
```

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
vpn-passthrough run-process --in-tunnel my-tunnel --restart-every 60 my-app
```

| Option | Description |
|--------|-------------|
| `--in-tunnel NAME` | Use an existing named tunnel |
| `--region-id REGION` | PIA region for an ephemeral tunnel |
| `--vpn-user USERNAME` | PIA username |
| `--vpn-password PASSWORD` | PIA password |
| `--restart-every SECONDS` | Kill and restart the process every N seconds |
| `--kill-with SIGNAL` | Signal used for restart (default: `SIGTERM`) |

If `--in-tunnel` is omitted, an ephemeral tunnel is created for the duration of the command.

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

Lists available PIA VPN regions.

```bash
vpn-passthrough list-regions
vpn-passthrough list-regions --format json
```

---

## Security Considerations

- The daemon must run as root (network namespace and nftables manipulation require `CAP_NET_ADMIN` and `CAP_SYS_ADMIN`).
- The Unix socket is owned by the `vpn-passthrough` group (mode `0660`). Add trusted users to this group to grant access.
- DNS leak prevention is enforced via nftables rules inside each namespace that drop outgoing DNS traffic on the veth interface, ensuring all DNS queries route through the VPN tunnel.
