import base64
import json

from radium226.vpn_passthrough.pia._gateway import _decode_port
from radium226.vpn_passthrough.pia._models import Payload


def test_decode_port() -> None:
    inner = json.dumps({"port": 54321, "expires_at": "2026-06-01T00:00:00"}).encode()
    payload = Payload(base64.b64encode(inner).decode())
    assert _decode_port(payload) == 54321
