# Hardcoded OpenVPN options in _openvpn.py

**File**: `packages/pia/src/radium226/vpn_passthrough/pia/_openvpn.py`
**Priority**: Low

## Problem

Many OpenVPN connection parameters are hardcoded (cipher, auth protocol,
verb level, persist-key, etc.) in the subprocess command list. There is no way
to override them without modifying source code.

## Fix

Expose the most useful ones as parameters to `openvpn_connected()`:
- `verb: int = 3` — log verbosity
- `cipher: str = "aes-256-gcm"` — cipher suite
- `extra_args: list[str] = []` — escape hatch for arbitrary flags

Keep defaults matching the current hardcoded values so there is no behaviour
change.
