from types import EllipsisType
from typing import Callable
from subprocess import run

import dill


def sudo(user: str | EllipsisType = ...):
    def decorator(func: Callable[..., ...]) -> Callable[..., ...]:
        def closure(*args, **kwargs):
            input_payload = {
                "func": func,
                "args": args,
                "kwargs": kwargs,
            }
            input_bytes = dill.dumps(input_payload)

            sudo_command_part = ["sudo", "--preserve-env"] + ([f"--user={user}"] if user is not ... else [])
            python_command_part = ["python", "-m", "vpn_passthrough.sudo"]
            command = sudo_command_part + python_command_part
            output_bytes = run(command, input=input_bytes, check=True, capture_output=True).stdout
            output_payload = dill.loads(output_bytes)
            return output_payload

        return closure
    return decorator