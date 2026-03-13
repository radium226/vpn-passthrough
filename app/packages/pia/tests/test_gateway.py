import base64
import json

from radium226.vpn_passthrough.pia import PIABackend
from radium226.vpn_passthrough.pia._models import Payload


def test_decode_port() -> None:
    inner = json.dumps({"port": 54321, "expires_at": "2026-06-01T00:00:00"}).encode()
    payload = Payload(base64.b64encode(inner).decode())
    assert PIABackend()._decode_port(payload) == 54321
