from os import environ
from inspect import signature
from enum import StrEnum
from ipaddress import IPv4Address


def parse(annotation, value):
    if issubclass(annotation, StrEnum):
        return annotation(value)
    elif annotation == IPv4Address:
        return IPv4Address(value)
    else:
        raise Exception("Unsupported type annotation! ")


def bind_args_from_env():
    def decorator(func):
        def closure():
            params = signature(func).parameters
            kwargs = {}
            for param_name, param in params.items():
                kwargs[param_name] = param.annotation(environ[param_name])
        
            func(**kwargs)
        
        return closure
    return decorator