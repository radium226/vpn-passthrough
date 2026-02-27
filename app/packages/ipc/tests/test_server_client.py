import asyncio
import os
from pathlib import Path
from typing import Annotated, Literal, Never

import pytest
from pydantic import BaseModel, Discriminator, TypeAdapter

from radium226.vpn_passthrough.ipc.ipc import open_client, open_server
from radium226.vpn_passthrough.ipc.protocol import Codec, Emit, Request, RequestHandler, ResponseHandler


# -- Test messages --


class Pong(BaseModel):
    request_id: str
    value: str
    type: Literal["pong"] = "pong"


class Ping(BaseModel, Request[Pong, Never]):
    id: str
    value: str
    type: Literal["ping"] = "ping"


class Progress(BaseModel):
    percent: int
    type: Literal["progress"] = "progress"


class Done(BaseModel):
    request_id: str
    result: str
    type: Literal["done"] = "done"


class Work(BaseModel, Request[Done, Progress]):
    id: str
    steps: int
    type: Literal["work"] = "work"


_ALL_TYPES = Ping | Pong | Work | Done | Progress
_TYPE_ADAPTER = TypeAdapter(Annotated[_ALL_TYPES, Discriminator("type")])


def _encode(msg: _ALL_TYPES) -> bytes:
    return msg.model_dump_json().encode()


def _decode(data: bytes) -> _ALL_TYPES:
    return _TYPE_ADAPTER.validate_json(data.decode())


CODEC = Codec[Ping | Work, Progress, Pong | Done](encode=_encode, decode=_decode)


@pytest.fixture
def socket_path(tmp_path: Path) -> Path:
    return tmp_path / "test.sock"


@pytest.mark.asyncio
async def test_request_response(socket_path: Path):
    async def handle_ping(request: Ping, fds: list[int], emit: Emit[Never]) -> tuple[Pong, list[int]]:
        return Pong(request_id=request.id, value=request.value.upper()), []

    async with open_server(socket_path, CODEC, handlers=[RequestHandler(request_type=Ping, on_request=handle_ping)]):
        async with open_client(socket_path, CODEC) as client:
            result_value = ""

            async def on_response(response: Pong | Done, fds: list[int]) -> None:
                nonlocal result_value
                match response:
                    case Pong(value=v):
                        result_value = v

            await client.request(
                Ping(id="1", value="hello"),
                handler=ResponseHandler(on_response=on_response),
            )

            assert result_value == "HELLO"


@pytest.mark.asyncio
async def test_events_and_response(socket_path: Path):
    async def handle_work(request: Work, fds: list[int], emit: Emit[Progress]) -> tuple[Done, list[int]]:
        for i in range(request.steps):
            await emit(Progress(percent=(i + 1) * 100 // request.steps), [])
        return Done(request_id=request.id, result="finished"), []

    async with open_server(socket_path, CODEC, handlers=[RequestHandler(request_type=Work, on_request=handle_work)]):
        async with open_client(socket_path, CODEC) as client:
            events: list[int] = []
            result = ""

            async def on_event(event: Progress, fds: list[int]) -> None:
                events.append(event.percent)

            async def on_response(response: Pong | Done, fds: list[int]) -> None:
                nonlocal result
                match response:
                    case Done(result=r):
                        result = r

            await client.request(
                Work(id="1", steps=4),
                handler=ResponseHandler(on_event=on_event, on_response=on_response),
            )

            assert events == [25, 50, 75, 100]
            assert result == "finished"


@pytest.mark.asyncio
async def test_fd_passing(socket_path: Path):
    async def handle_ping(request: Ping, fds: list[int], emit: Emit[Never]) -> tuple[Pong, list[int]]:
        assert len(fds) == 1
        content = os.read(fds[0], 4096)
        os.close(fds[0])
        return Pong(request_id=request.id, value=content.decode()), []

    async with open_server(socket_path, CODEC, handlers=[RequestHandler(request_type=Ping, on_request=handle_ping)]):
        async with open_client(socket_path, CODEC) as client:
            result_value = ""

            async def on_response(response: Pong | Done, fds: list[int]) -> None:
                nonlocal result_value
                match response:
                    case Pong(value=v):
                        result_value = v

            r, w = os.pipe()
            os.write(w, b"fd-content")
            os.close(w)

            await client.request(
                Ping(id="1", value="check-fd"),
                fds=[r],
                handler=ResponseHandler(on_response=on_response),
            )

            assert result_value == "fd-content"


@pytest.mark.asyncio
async def test_multiple_concurrent_requests(socket_path: Path):
    async def handle_ping(request: Ping, fds: list[int], emit: Emit[Never]) -> tuple[Pong, list[int]]:
        await asyncio.sleep(0.01)
        return Pong(request_id=request.id, value=request.value), []

    async with open_server(socket_path, CODEC, handlers=[RequestHandler(request_type=Ping, on_request=handle_ping)]):
        async with open_client(socket_path, CODEC) as client:
            results: dict[str, str] = {}

            async def make_request(req_id: str, value: str) -> None:
                async def on_response(response: Pong | Done, fds: list[int]) -> None:
                    match response:
                        case Pong(value=v):
                            results[req_id] = v

                await client.request(
                    Ping(id=req_id, value=value),
                    handler=ResponseHandler(on_response=on_response),
                )

            await asyncio.gather(
                make_request("a", "alpha"),
                make_request("b", "beta"),
                make_request("c", "gamma"),
            )

            assert results == {"a": "alpha", "b": "beta", "c": "gamma"}
