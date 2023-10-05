from subprocess import Popen, STDOUT
from cherrypy import expose, quickstart, tools, config
from contextlib import contextmanager
from sys import stdout, stderr
from time import sleep
import requests
from importlib import import_module
from inspect import getmembers, isfunction, ismodule, getmodule
from functools import wraps
from pathlib import Path


class Server():

    def __init__(self, unix_socket_path: Path):
        self.unix_socket_path = unix_socket_path

    @expose()
    def execute(self)
        ...


class Client()

    def execute(self, func):
        ...


def random_unix_socket_path() -> Path:
    ...


def switchable()
    def decorator(func):
        func_name = func.__name__
        module_name = func.__module__    
        @wraps(func)
        def closure(sudo: bool | None = None, user: str | None = None, network_namespace: str | None = None, *kwargs):
            unix_socket_path: Path = random_unix_socket_path()
            with Server(unix_socket_path=unix_socket_path, func_name=func_name, module_name=module_name) as server:
                client = Client(unix_socket_path=unix_socket_path)
                return client.execute(kwargs)


# def sudo():
#     def decorator(func):
#         func.sudo = True
#         func_name == func.__name__
#         def closure(**kwargs):
#             response = requests.post(f"http://localhost:8080/{func_name}", json=kwargs)
#             return response.json()
#         return closure
#     return decorator


class Teleporter():

    def __init__(self, command: list[str] = []):
        self.command = command

    def __call__(self):
        def decorator(func):
            func_name = func.__name__
            module_name = func.__module__
            @wraps(func)
            def closure(*args, **kwargs):
                with self.server():
                    sleep(100)
                    response = requests.get(f"http://localhost:8080?fqn={module_name}:{func_name}")
                    return response.json()
                closure.teleported_func = func
            return closure
        return decorator

    @contextmanager
    def server(self):
        command = self.command + ["python", "-u", "-m", "vpn_passthrough.teleporter"]
        process = Popen(command, stdout=stdout, stderr=stderr)
        yield
        process.kill()
        

    @expose()
    @tools.json_out()
    def index(self, fqn):
        [module_name, func_name] = fqn.split(":")
        func = getattr(__import__(module_name, fromlist=[func_name]), func_name)
        print(func)
        return func.__wrapped__()

    def serve_forever(self):
        #config.update({
        #    "global": {
        #        "environment" : "production",
        #    },
        #})
        return quickstart(self)


sudo = Teleporter(command=["sudo"])