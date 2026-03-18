import asyncio
import types as _types
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Any, Never, get_args, get_origin, Union

from loguru import logger

from .protocol import Codec, Request, Response, ResponseHandler, validate_response, _resolve_type
from .transport import Connection, Frame, Framing, NullCharFraming, open_connection


def _flatten_event_types(t: Any) -> list[type]:
    """Return the list of concrete types from a possibly-Union event type, excluding Never."""
    if t is Never:
        return []
    origin = get_origin(t)
    if origin is Union or isinstance(t, _types.UnionType):
        result: list[type] = []
        for arg in get_args(t):
            result.extend(_flatten_event_types(arg))
        return result
    if isinstance(t, type):
        return [t]
    return []


class Client[RequestT: Request, EventT, ResponseT: Response]():
    def __init__(
        self,
        connection: Connection,
        codec: Codec[RequestT, EventT, ResponseT],
    ) -> None:
        self._connection = connection
        self._codec = codec
        self._pending: dict[str, tuple[asyncio.Future[None], RequestT, ResponseHandler[EventT, ResponseT]]] = {}
        self._event_routing: dict[type, list[str]] = {}  # concrete event type -> [request_id]
        self._receive_task: asyncio.Task = asyncio.create_task(self._receive_loop())

    @classmethod
    async def _connect(
        cls,
        socket_path: Path,
        codec: Codec[RequestT, EventT, ResponseT],
        framing: Framing = NullCharFraming(),
    ) -> "Client[RequestT, EventT, ResponseT]":
        connection = await open_connection(socket_path, framing)
        return cls(connection, codec)

    def _register_event_routing(self, request_id: str, request: RequestT) -> None:
        event_type = getattr(request.__class__, "__event_type__", None)
        if event_type is None:
            return
        event_type = _resolve_type(event_type, type(request))
        for event_type_class in _flatten_event_types(event_type):
            self._event_routing.setdefault(event_type_class, []).append(request_id)

    def _unregister_event_routing(self, request_id: str, request: RequestT) -> None:
        event_type = getattr(request.__class__, "__event_type__", None)
        if event_type is None:
            return
        event_type = _resolve_type(event_type, type(request))
        for event_type_class in _flatten_event_types(event_type):
            lst = self._event_routing.get(event_type_class)
            if lst is not None:
                lst[:] = [rid for rid in lst if rid != request_id]
                if not lst:
                    del self._event_routing[event_type_class]

    async def request(
        self,
        request: RequestT,
        fds: list[int] | None = None,
        handler: ResponseHandler[EventT, ResponseT] | None = None,
    ) -> None:
        if fds is None:
            fds = []
        if handler is None:
            handler = ResponseHandler()
        loop = asyncio.get_running_loop()
        future: asyncio.Future[None] = loop.create_future()
        self._pending[request.id] = (future, request, handler)
        self._register_event_routing(request.id, request)
        try:
            await self._connection.send_frame(Frame(self._codec.encode(request), fds))
            await future
        finally:
            self._unregister_event_routing(request.id, request)

    async def _receive_loop(self) -> None:
        try:
            async for frame in self._connection:
                try:
                    message = self._codec.decode(frame.data)
                    match message:
                        case Response() as response:
                            entry = self._pending.pop(response.request_id, None)
                            if entry is not None:
                                future, original_request, response_handler = entry
                                validate_response(original_request, response)
                                if response_handler.on_response is not None:
                                    await response_handler.on_response(response, frame.fds)
                                if not future.done():
                                    future.set_result(None)
                        case event:
                            request_ids = self._event_routing.get(type(event), [])
                            for request_id in list(request_ids):
                                entry = self._pending.get(request_id)
                                if entry is not None:
                                    _, _, response_handler = entry
                                    if response_handler.on_event is not None:
                                        await response_handler.on_event(event, frame.fds)
                except Exception:
                    logger.exception("Error processing received frame (data={!r}, fds={}), skipping", frame.data, frame.fds)
        finally:
            for request_id, (future, _, _) in list(self._pending.items()):
                if not future.done():
                    future.set_exception(ConnectionError("Connection closed"))
            self._pending.clear()
            self._event_routing.clear()

    async def aclose(self) -> None:
        self._receive_task.cancel()
        try:
            await self._receive_task
        except asyncio.CancelledError:
            pass
        for request_id, (future, _, _) in list(self._pending.items()):
            if not future.done():
                future.cancel()
        self._pending.clear()
        self._event_routing.clear()
        await self._connection.aclose()

    @classmethod
    @asynccontextmanager
    async def connect(
        cls,
        socket_path: Path,
        codec: Codec[RequestT, EventT, ResponseT],
        framing: Framing = NullCharFraming(),
    ) -> AsyncIterator["Client[RequestT, EventT, ResponseT]"]:
        client = await cls._connect(socket_path, codec, framing)
        try:
            yield client
        finally:
            await client.aclose()
