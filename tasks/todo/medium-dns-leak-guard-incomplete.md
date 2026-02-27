# DNS leak guard only blocks port 53

**File**: `packages/server/src/radium226/vpn_passthrough/server/dns_leak_guard.py`
**Priority**: Medium

## Problem

`DnsLeakGuard` loads nftables rules that drop outgoing UDP/TCP traffic on
port 53 via the vpeer interface. This guards against classic DNS leaks.

However, modern DNS transports are unguarded:
- **DNS-over-HTTPS (DoH)** — port 443, indistinguishable from HTTPS traffic
- **DNS-over-TLS (DoT)** — port 853

A process inside the tunnel that uses DoH or DoT (e.g. Firefox with its
built-in DoH resolver, or `systemd-resolved` with DoT) will route queries
through the veth to the host, leaking DNS queries outside the VPN.

## Fix

Options in increasing strictness:
1. Also block ports 853 (DoT) via vpeer — easy.
2. Use a default-deny egress policy on the vpeer interface and only allow
   VPN tunnel traffic — most robust but may break legitimate LAN access.
3. Document the limitation clearly so operators know to disable DoH in
   applications running inside the tunnel.

Port 853 block is a quick win; default-deny is the correct long-term fix.
