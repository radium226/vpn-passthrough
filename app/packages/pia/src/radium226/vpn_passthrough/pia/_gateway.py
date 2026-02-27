import asyncio
import base64
import json
from collections.abc import Callable

import httpx
from loguru import logger

from ._models import Auth, ForwardedPort, Payload, PayloadAndSignature, Signature
from ._run import run

_REBIND_INTERVAL = 30.0


async def _get_auth_token(auth: Auth) -> str:
    async with httpx.AsyncClient() as http:
        response = await http.post(
            "https://privateinternetaccess.com/api/client/v2/token",
            data={"username": auth.user, "password": auth.password},
            timeout=10.0,
        )
        response.raise_for_status()
    return response.json()["token"]


async def _get_port_signature(
    gateway_ip: str, token: str, enter_netns: Callable[[], None]
) -> PayloadAndSignature:
    # The gateway is only reachable from inside the netns and uses a self-signed
    # certificate, so we reach it via curl run inside the namespace.
    _, stdout = await run(
        [
            "curl", "--silent", "--insecure", "-G",
            "--data-urlencode", f"token={token}",
            f"https://{gateway_ip}:19999/getSignature",
        ],
        check=True,
        preexec_fn=enter_netns,
    )
    data = json.loads(stdout)
    return PayloadAndSignature(
        payload=Payload(data["payload"]),
        signature=Signature(data["signature"]),
    )


def _decode_port(payload: Payload) -> int:
    return json.loads(base64.b64decode(payload))["port"]


async def _bind_port(
    gateway_ip: str, pas: PayloadAndSignature, enter_netns: Callable[[], None]
) -> None:
    _, stdout = await run(
        [
            "curl", "--silent", "--insecure", "-G",
            "--data-urlencode", f"payload={pas.payload}",
            "--data-urlencode", f"signature={pas.signature}",
            f"https://{gateway_ip}:19999/bindPort",
        ],
        check=True,
        preexec_fn=enter_netns,
    )
    data = json.loads(stdout)
    if data.get("status") != "OK":
        logger.warning("Unexpected bindPort response: {}", data)


async def allocate_forwarded_port(
    gateway_ip: str, auth: Auth, enter_netns: Callable[[], None]
) -> ForwardedPort:
    """Request a forwarded port from the PIA gateway and perform the initial bind."""
    token = await _get_auth_token(auth)
    pas = await _get_port_signature(gateway_ip, token, enter_netns)
    port = _decode_port(pas.payload)
    await _bind_port(gateway_ip, pas, enter_netns)
    logger.info("Forwarded port {} allocated", port)
    return ForwardedPort(number=port, payload_and_signature=pas)


async def rebind_loop(
    gateway_ip: str,
    forwarded_port: ForwardedPort,
    enter_netns: Callable[[], None],
    interval: float = _REBIND_INTERVAL,
) -> None:
    """Periodically rebind *forwarded_port* to keep it alive on the PIA gateway."""
    while True:
        await asyncio.sleep(interval)
        try:
            await _bind_port(gateway_ip, forwarded_port.payload_and_signature, enter_netns)
            logger.debug("Port {} rebound", forwarded_port.number)
        except Exception:
            logger.warning(
                "Failed to rebind port {}, will retry in {}s",
                forwarded_port.number,
                interval,
            )
