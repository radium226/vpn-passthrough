import asyncio
from pathlib import Path

import pytest

from radium226.vpn_passthrough.ipc.transport import (
    Frame,
    accept_connections,
    open_connection,
)


@pytest.fixture
def socket_path(tmp_path: Path) -> Path:
    return tmp_path / "test.sock"


@pytest.mark.asyncio
async def test_send_receive_frame(socket_path: Path):
    received: list[Frame] = []

    async def accept_one():
        async for conn in accept_connections(socket_path):
            frame = await conn.receive_frame()
            received.append(frame)
            await conn.send_frame(Frame(b"pong"))
            await conn.aclose()
            break

    server_task = asyncio.create_task(accept_one())
    await asyncio.sleep(0.05)

    conn = await open_connection(socket_path)
    await conn.send_frame(Frame(b"ping"))
    reply = await conn.receive_frame()
    await conn.aclose()

    await server_task

    assert received[0].data == b"ping"
    assert reply.data == b"pong"


@pytest.mark.asyncio
async def test_multiple_frames(socket_path: Path):
    count = 5
    received: list[bytes] = []

    async def accept_one():
        async for conn in accept_connections(socket_path):
            for _ in range(count):
                frame = await conn.receive_frame()
                received.append(frame.data)
                await conn.send_frame(Frame(frame.data))
            await conn.aclose()
            break

    server_task = asyncio.create_task(accept_one())
    await asyncio.sleep(0.05)

    conn = await open_connection(socket_path)
    replies = []
    for i in range(count):
        await conn.send_frame(Frame(f"msg-{i}".encode()))
        reply = await conn.receive_frame()
        replies.append(reply.data)
    await conn.aclose()

    await server_task

    for i in range(count):
        assert received[i] == f"msg-{i}".encode()
        assert replies[i] == f"msg-{i}".encode()


@pytest.mark.asyncio
async def test_large_message(socket_path: Path):
    payload = b"x" * 16384  # 16KB, larger than 4096 buffer

    async def accept_one():
        async for conn in accept_connections(socket_path):
            frame = await conn.receive_frame()
            await conn.send_frame(Frame(frame.data))
            await conn.aclose()
            break

    server_task = asyncio.create_task(accept_one())
    await asyncio.sleep(0.05)

    conn = await open_connection(socket_path)
    await conn.send_frame(Frame(payload))
    reply = await conn.receive_frame()
    await conn.aclose()

    await server_task

    assert reply.data == payload
