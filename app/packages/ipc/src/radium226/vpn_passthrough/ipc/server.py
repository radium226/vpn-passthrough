import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from loguru import logger

from .protocol import Codec, Request, RequestHandler, Response, validate_event, validate_response
from .transport import Connection, Frame, Framing, NullCharFraming, accept_connections, is_socket_activated


class Server[RequestT: Request, EventT, ResponseT: Response]():
    def __init__(
        self,
        socket_path: Path,
        handlers: list[RequestHandler[Any, Any, Any]],
        codec: Codec[RequestT, EventT, ResponseT],
        framing: Framing = NullCharFraming(),
    ) -> None:
        self._socket_path = socket_path
        self._handler_map: dict[type, RequestHandler[Any, Any, Any]] = {h.request_type: h for h in handlers}
        self._codec = codec
        self._framing = framing
        self._connections: list[Connection] = []

    async def _handle_connection(self, connection: Connection) -> None:
        self._connections.append(connection)
        logger.info("Client connected (total connections: {})", len(self._connections))

        try:
            async for frame in connection:
                logger.debug("Received frame ({} bytes, {} fds)", len(frame.data), len(frame.fds))
                try:
                    message = self._codec.decode(frame.data)
                except Exception:
                    logger.warning("Failed to decode frame ({} bytes), skipping", len(frame.data))
                    continue

                match message:
                    case Request() as request:
                        logger.info("Received request {} (id={})", type(request).__name__, request.id)

                        async def handle_request(request: RequestT, fds: list[int]) -> None:
                            async def emit(event: EventT, fds: list[int] | None = None) -> None:
                                validate_event(request, event)
                                logger.debug("Emitting event {} for request {}", type(event).__name__, request.id)
                                data = self._codec.encode(event)
                                try:
                                    await connection.send_frame(Frame(data, fds or []))
                                except (OSError, EOFError):
                                    logger.warning("Client disconnected during event emit for request {}", request.id)

                            try:
                                request_handler = self._handler_map.get(type(request))
                                if request_handler is None:
                                    raise ValueError(f"No handler registered for {type(request).__name__}")
                                response, response_fds = await request_handler.on_request(request, fds, emit)
                                validate_response(request, response)
                                logger.info("Sending response {} for request {} ({} fds)", type(response).__name__, request.id, len(response_fds))
                                await connection.send_frame(
                                    Frame(self._codec.encode(response), response_fds)
                                )
                            except Exception:
                                logger.exception("Handler raised an exception for request {} (id={})", type(request).__name__, request.id)

                        asyncio.create_task(handle_request(request, frame.fds))

                    case _:
                        logger.warning("Received non-Request message: {}", type(message).__name__)
        finally:
            if connection in self._connections:
                self._connections.remove(connection)
            logger.info("Client disconnected (remaining connections: {})", len(self._connections))
            await connection.aclose()

    async def serve(self) -> None:
        logger.info("Server listening on {}", self._socket_path)
        async for connection in accept_connections(self._socket_path, self._framing):
            asyncio.create_task(self._handle_connection(connection))

    async def wait_forever(self) -> None:
        await asyncio.get_running_loop().create_future()

    async def aclose(self) -> None:
        logger.info("Server shutting down ({} active connections)", len(self._connections))
        for connection in list(self._connections):
            await connection.aclose()
        self._connections.clear()
        if not is_socket_activated() and self._socket_path.exists():
            self._socket_path.unlink()
            logger.debug("Removed socket file {}", self._socket_path)

    @classmethod
    @asynccontextmanager
    async def open(
        cls,
        socket_path: Path,
        handlers: list[RequestHandler[Any, Any, Any]],
        codec: Codec[RequestT, EventT, ResponseT],
        framing: Framing = NullCharFraming(),
    ) -> AsyncIterator["Server[RequestT, EventT, ResponseT]"]:
        server: Server[RequestT, EventT, ResponseT] = cls(socket_path, handlers, codec, framing)
        try:
            yield server
        finally:
            await server.aclose()

    @classmethod
    @asynccontextmanager
    async def listen(
        cls,
        socket_path: Path,
        handlers: list[RequestHandler[Any, Any, Any]],
        codec: Codec[RequestT, EventT, ResponseT],
        framing: Framing = NullCharFraming(),
    ) -> AsyncIterator["Server[RequestT, EventT, ResponseT]"]:
        _POLL_INTERVAL = 0.01
        _POLL_TIMEOUT = 5.0
        async with cls.open(socket_path, handlers, codec, framing) as server:
            serving_task = asyncio.create_task(server.serve())
            if not is_socket_activated():
                elapsed = 0.0
                while not socket_path.exists():
                    await asyncio.sleep(_POLL_INTERVAL)
                    elapsed += _POLL_INTERVAL
                    if serving_task.done() and not serving_task.cancelled():
                        exc = serving_task.exception()
                        if exc is not None:
                            raise exc
                    if elapsed >= _POLL_TIMEOUT:
                        serving_task.cancel()
                        raise TimeoutError(
                            f"Server socket {socket_path} did not appear within {_POLL_TIMEOUT}s"
                        )
            try:
                yield server
            finally:
                serving_task.cancel()
                try:
                    await serving_task
                except asyncio.CancelledError:
                    pass
                except BaseException:
                    raise
