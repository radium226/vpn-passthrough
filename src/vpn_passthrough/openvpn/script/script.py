from dataclasses import dataclass, field
from ipaddress import IPv4Address
from pathlib import Path
from threading import Event
from typing import Any, TypeAlias
from queue import Queue
from httpx import HTTPTransport, Client

from vpn_passthrough.http_server.http_server import Verb, URL

from ...http_server import HTTPServer, JSONRoute


UpInfo: TypeAlias = dict


class UpRoute(JSONRoute):

    queue: Queue = Queue(maxsize=1)

    def matches(self, verb: Verb, url: URL) -> bool:
        print(f"url={url}")
        return verb == Verb.POST and url == URL("/up")
    
    def handle(self, input: dict) -> dict:
        print("We are here! ")
        self.queue.put(input)
        return {}

    def wait_for(self) -> dict:
        return self.queue.get()


class DebugRoute(JSONRoute):

    event: Event = Event()

    def matches(self, verb: Verb, url: URL) -> bool:
        return verb == Verb.POST and url == URL("/debug")
    
    def handle(self, input: dict) -> dict:
        self.event.set()
        return {}

    def wait_for(self) -> None:
        self.event.wait()


@dataclass
class ScriptServer():

    socket_path: Path = Path("/tmp/vpn-passthrough-openvpn-script.sock")

    up_route: UpRoute = field(default_factory=UpRoute)

    debug_route: DebugRoute = field(default_factory=DebugRoute)

    http_server: HTTPServer = field(init=False)

    def __post_init__(self):
        self.http_server = (
            HTTPServer(socket_path=self.socket_path)
                .with_route(self.up_route)
                .with_route(self.debug_route)
        )

    def start(self) -> None:
        self.http_server.start()

    def wait_for_up(self) -> UpInfo:
        return self.up_route.wait_for()
    
    def wait_for_debug(self) -> None:
        return self.debug_route.wait_for()
    
    def stop(self):
        self.http_server.stop()

    def __enter__(self):
        self.start()
        return self
    
    def __exit__(self, type, value, traceback):
        self.stop()


@dataclass
class ScriptClient():

    socket_path: Path = Path("/tmp/vpn-passthrough-openvpn-script.sock")

    def debug(self) -> None:
        transport = HTTPTransport(uds=str(self.socket_path))
        with Client(
            transport=transport,
            headers={
                "Connection": "close",
            },
        ) as client:
            client.post(
                "http://localhost/debug",
                json={}
            )

    def up(self, info: UpInfo) -> None:
        transport = HTTPTransport(uds=str(self.socket_path))
        with Client(
            transport=transport,
            headers={
                "Connection": "close",
            },
        ) as client:
            response = client.post(
                "http://localhost/up",
                json=info,
            )
            print(response.json())
            print("And now we are here! ")