from typing import Any, Generic, Protocol, TypeVar
from dataclasses import dataclass, field
from enum import StrEnum, auto
from threading import Thread
from typing import NewType, TypeAlias
from http.server import BaseHTTPRequestHandler
from socketserver import UnixStreamServer
from pathlib import Path
import json


class UnixSocketHTTPServer(UnixStreamServer):

    def get_request(self):
        request, _ = super(UnixSocketHTTPServer, self).get_request()
        return (request, ["local", 0])


class Verb(StrEnum):

    GET = auto()
    
    POST = auto()
    
    PUT = auto()
    
    DELETE = auto()


URL = NewType("URL", str)


RI = TypeVar("RI", covariant=True)


RO = TypeVar("RO", covariant=True)


I = TypeVar("I")


O = TypeVar("O")


class RouteInput(Generic[RI], Protocol):
    ...

class RouteOutput(Generic[RO], Protocol):
    ...

class Route(RouteInput[I], RouteOutput[O], Protocol):

    def parse_input(self, input_bytes: bytes) -> I:
        ...

    def format_output(self, output: O) -> bytes:
        ...

    def matches(self, verb: Verb, url: URL) -> bool:
        ...

    def handle(self, input: I) -> O:
        ...


class JSONRoute(Route[dict, dict], Protocol):

    def parse_input(self, input_bytes: bytes) -> dict:
        input_str = input_bytes.decode("utf-8")
        print(f"input_str={input_str}")
        return json.loads(input_str)

    def format_output(self, output: dict) -> bytes:
        output_str = json.dumps(output)
        print(f"output_str={output_str}")
        output_bytes = output_str.encode("utf-8")
        return output_bytes


@dataclass
class HTTPServer():

    socket_path: Path

    routes: list[Route[Any, Any]] = field(default_factory=list)

    _server: UnixSocketHTTPServer | None = None

    _thread: Thread | None = None

    def with_route(self, route: Route[Any, Any]) -> "HTTPServer":
        self.routes.append(route)
        return self

    def start(self) -> None:
        if self.socket_path.exists():
            self.socket_path.unlink()

        routes = self.routes

        class Handler(BaseHTTPRequestHandler):

            def _handle(self, verb: Verb, url: URL) -> None:
                for route in routes:
                    if route.matches(verb, url):
                        try:
                            self.send_response(200)
                            self.end_headers()
                            input_bytes = self.rfile.read(int(self.headers["Content-Length"]))
                            input = route.parse_input(input_bytes)
                            output = route.handle(input)
                            output_bytes = route.format_output(output)
                            self.wfile.write(output_bytes)
                        except Exception as e:
                            print(str(e))
                            self.send_error(500, explain=str(e))

                        return

                self.send_error(404)

            def do_GET(self):
                self._handle(Verb.GET, URL(self.path))
                
            def do_POST(self):
                self._handle(Verb.POST, URL(self.path))


        self._server = UnixSocketHTTPServer((str(self.socket_path)), Handler)

        def serve_forever(server):
            server.serve_forever()
            
        self._thread = Thread(target=serve_forever, args=(self._server,))
        self._thread.start()

    def stop(self) -> None:
        if server := self._server:
            server.shutdown()

    def __enter__(self) -> "HTTPServer":
        self.start()
        return self
    
    def __exit__(self, type, value, traceback) -> None:
        self.stop()

    def wait_for(self) -> None:
        if thread := self._thread:
            thread.join()