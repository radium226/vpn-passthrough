import sys
from typing import Any, Awaitable, Callable, ForwardRef, Protocol, runtime_checkable, get_args, get_origin
from dataclasses import dataclass


class Request[ResponseT, EventT]:
    """Base class for requests. Phantom-typed with expected ResponseT and EventT.

    Concrete subclasses must inherit from ``Request[SomeResponse, SomeEvent]``
    so that ``__response_type__`` and ``__event_type__`` are populated at class
    creation time via ``__init_subclass__``.
    """

    id: str

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        for base in getattr(cls, "__orig_bases__", ()):
            origin = get_origin(base)
            if origin is Request:
                args = get_args(base)
                if len(args) == 2:
                    cls.__response_type__ = args[0]
                    cls.__event_type__ = args[1]
                    return


@runtime_checkable
class Response(Protocol):
    """Structural protocol: any object with `request_id: str` is a response."""
    request_id: str


def _type_name(t: Any) -> str:
    if hasattr(t, "__name__"):
        return t.__name__
    return str(t)


def _resolve_type(t: Any, cls: type) -> Any:
    """Resolve a ForwardRef using the module namespace of *cls*."""
    if isinstance(t, ForwardRef):
        module = sys.modules.get(cls.__module__)
        ns = vars(module) if module else {}
        return eval(t.__forward_arg__, ns)
    return t


def validate_response(request: Request[Any, Any], response: Any) -> None:
    """Validate that *response* matches the request's phantom ``ResponseT``."""
    try:
        expected = request.__class__.__response_type__
    except AttributeError:
        raise TypeError(
            f"{type(request).__name__} does not specify type parameters; "
            f"inherit from Request[ResponseT, EventT]"
        )
    expected = _resolve_type(expected, type(request))
    if not isinstance(response, expected):
        raise TypeError(
            f"Request {type(request).__name__} expects response of type "
            f"{_type_name(expected)}, got {type(response).__name__}"
        )


def validate_event(request: Request[Any, Any], event: Any) -> None:
    """Validate that *event* matches the request's phantom ``EventT``."""
    try:
        expected = request.__class__.__event_type__
    except AttributeError:
        raise TypeError(
            f"{type(request).__name__} does not specify type parameters; "
            f"inherit from Request[ResponseT, EventT]"
        )
    expected = _resolve_type(expected, type(request))
    if not isinstance(event, expected):
        raise TypeError(
            f"Request {type(request).__name__} expects event of type "
            f"{_type_name(expected)}, got {type(event).__name__}"
        )


type Emit[EventT] = Callable[[EventT, list[int]], Awaitable[None]]

type OnRequest[RequestT: Request, EventT, ResponseT: Response] = Callable[
    [RequestT, list[int], Emit[EventT]],
    Awaitable[tuple[ResponseT, list[int]]]
]


@dataclass
class RequestHandler[RequestT: Request, EventT, ResponseT: Response]:
    request_type: type[RequestT]
    on_request: OnRequest[RequestT, EventT, ResponseT]


type Encode[MessageT] = Callable[[MessageT], bytes]

type Decode[MessageT] = Callable[[bytes], MessageT]


@dataclass
class Codec[RequestT: Request, EventT, ResponseT: Response]():
    encode: Encode[RequestT | EventT | ResponseT]
    decode: Decode[RequestT | EventT | ResponseT]


type OnEvent[EventT] = Callable[[EventT, list[int]], Awaitable[None]]


type OnResponse[ResponseT: Response] = Callable[[ResponseT, list[int]], Awaitable[None]]


@dataclass
class ResponseHandler[EventT, ResponseT: Response]():
    """Data class bundling event and response handlers for a request."""
    on_event: OnEvent[EventT] | None = None
    on_response: OnResponse[ResponseT] | None = None
