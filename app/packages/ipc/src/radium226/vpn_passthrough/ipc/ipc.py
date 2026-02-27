from contextlib import AbstractAsyncContextManager
from pathlib import Path
from typing import Any

from .client import Client
from .protocol import Codec, Request, RequestHandler, Response  # noqa: F401
from .server import Server
from .transport import Framing, NullCharFraming


def open_server[RequestT: Request, EventT, ResponseT: Response](
    socket_path: Path,
    codec: Codec[RequestT, EventT, ResponseT],
    *,
    handlers: list[RequestHandler[Any, Any, Any]],
    framing: Framing = NullCharFraming(),
) -> AbstractAsyncContextManager[Server[RequestT, EventT, ResponseT]]:
    return Server.listen(socket_path, handlers, codec, framing)


def open_client[RequestT: Request, EventT, ResponseT: Response](
    socket_path: Path,
    codec: Codec[RequestT, EventT, ResponseT],
    *,
    framing: Framing = NullCharFraming(),
) -> AbstractAsyncContextManager[Client[RequestT, EventT, ResponseT]]:
    return Client.connect(socket_path, codec, framing)
