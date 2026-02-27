# Missing docstrings on key classes and methods

**Files**: various
**Priority**: Low

## Problem

Several complex classes and methods lack docstrings:

- `Service` class (`service.py`) — no class-level docstring explaining
  lifecycle, threading model, or state invariants.
- `handle_run_process()` — complex restart/rebind loop with no explanation of
  the state machine.
- `handle_create_tunnel()` — no explanation of the setup sequence or what
  happens if VPN credentials are absent.
- `internet.py` lines ~107-110 — both `iifname` and `oifname` rules are
  injected per forward chain with no explanation of why both directions are
  needed. This is the nftables multi-table `accept` limitation from MEMORY.md
  but it's not documented in the code.
- `_run.py` (PIA) — return type `tuple[int, bytes]` is not documented (bytes =
  captured stdout).

## Fix

Add concise docstrings (1-3 sentences) to each. For `internet.py`, add an
inline comment referencing the nftables multi-table `accept` behaviour.
