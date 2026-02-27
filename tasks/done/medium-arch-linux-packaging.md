# Add Arch Linux packaging

**Priority**: Medium

## Problem

There is no packaging for Arch Linux. The project cannot be installed via
`makepkg` or distributed through the AUR. Users must manually clone the repo
and manage the Python environment with `uv`.

## Fix

Create a `PKGBUILD` at the repo root (or in a dedicated `packaging/arch/`
directory) that:

- Builds and installs all six packages (`ipc`, `messages`, `server`, `client`,
  `app`, `pia`) using `uv build` + `pip install --root`
- Installs the `vpn-passthrough` binary to `/usr/bin/`
- Includes a systemd service unit (`vpn-passthrough.service`) that runs
  `vpn-passthrough start-server` as root, with `Restart=on-failure`
- Declares runtime dependencies: `python`, `openvpn`, `iproute2`, `nftables`,
  `curl`, and optionally `python-capng` (system package for ambient capabilities)
- Uses `install=vpn-passthrough.install` for post-install hints (e.g. `systemctl enable`)
