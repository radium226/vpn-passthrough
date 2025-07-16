# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a VPN passthrough application that creates isolated network namespaces for running applications through a PIA (Private Internet Access) VPN connection. The application is written in Python and uses Click for the CLI interface.

## Architecture

The codebase is organized under `src/radium226/vpn_passthrough/` with the following key components:

- **app.py**: Main CLI application using Click framework with commands for `exec`, `show-ip`, `test-dns-leak`, and PIA region management
- **vpn_passthrough.py**: Core VPN passthrough logic and context manager
- **pia.py**: PIA VPN provider integration for regions and credentials
- **models.py**: Type definitions and data classes
- **netns.py**: Network namespace management
- **openvpn.py**: OpenVPN client integration
- **dns.py**: DNS configuration handling
- **internet.py**: Internet routing and firewall rules

## Common Commands

### Development
- `make help` - Show available make targets
- `make run` - Run the application via `mise exec -- uv run vpn-passthrough`
- `make check` - Run all checks (mypy, ruff, pytest)

### Individual checks
- `make mypy` - Type checking with mypy
- `make ruff` - Linting with ruff
- `make pytest` - Run tests with pytest

### Application usage
- `vpn-passthrough exec <command>` - Execute command through VPN
- `vpn-passthrough show-ip` - Show current IP address through VPN
- `vpn-passthrough test-dns-leak` - Test for DNS leaks
- `vpn-passthrough pia list-regions` - List available PIA regions

## Environment Setup

The project uses:
- **mise** for tool management (uv, sops)
- **uv** for Python package management
- **Python 3.12+** required

## Configuration

- PIA credentials via `PIA_CREDENTIALS` environment variable or `--pia-credentials` option (format: `user:password`)
- PIA region via `PIA_REGION` environment variable or `--pia-region` option
- Optional name parameter for namespace identification

## Testing

Tests are located in `tests/` directory. The pytest configuration excludes output capture (`--capture=no`) for debugging.

## Type Checking

MyPy is configured with strict mode enabled. Type stubs are included for external dependencies like requests.