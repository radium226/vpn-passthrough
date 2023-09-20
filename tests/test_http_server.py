from typing import Any
from pytest import fixture

from pathlib import Path
from subprocess import run
from httpx import HTTPTransport, Client

from vpn_passthrough.http_server import HTTPServer, Route, Verb, URL


class PingPongRoute(Route[str, str]):

    def __init__(self):
        self._counter = 0

    def parse_input(self, input_bytes: bytes) -> str:
        return input_bytes.decode("utf-8")

    def format_output(self, output: str) -> bytes:
        return output.encode("utf-8")

    @property
    def counter(self) -> int:
        return self._counter

    def matches(self, verb: Verb, url: URL) -> bool:
        return verb == Verb.POST and url == URL("/")
    
    def handle(self, input: str) -> str:
        print(f"input={input}")
        if input == "ping":
            self._counter += 1
            return "pong"

        raise Exception(f"Invalid input (input={input})! ")


def test_ping_pong_route():
    route = PingPongRoute()
    with HTTPServer(Path("./test.socket")).with_route(route) as http_server:
        process = run(["curl", "-X", "POST", "--http0.9", "--unix-socket", "./test.socket", "http://localhost/", "--data", "ping"], capture_output=True, text=True)
        
        assert process.returncode == 0
        pong = process.stdout

    assert route.counter == 1
    assert pong == "pong"