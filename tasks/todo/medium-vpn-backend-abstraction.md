# Add VPN backend abstraction layer

**Priority**: Medium

## Problem

The server is tightly coupled to PIA/OpenVPN. Adding a second VPN provider
(e.g. WireGuard, Mullvad, or a generic OpenVPN config) would require forking
`handle_create_tunnel` rather than selecting a backend.

## Fix

Introduce a `VPNBackend` protocol (or abstract base class) in
`packages/server/` (or a new `packages/vpn/` package):

```python
class VPNBackend(Protocol):
    async def connect(self, netns: Namespace, config: VPNConfig) -> AsyncContextManager[VPNSession]: ...

@dataclass
class VPNSession:
    gateway_ip: str
    tun_ip: str
    dns_servers: list[str]
    forwarded_ports: list[int]
```

- Move the existing PIA logic into a `PIABackend` implementation
- `handle_create_tunnel` selects the backend based on a `backend` field in the
  request or server config
- `packages/pia` remains standalone; `PIABackend` lives in `packages/server/`
  and wraps it
