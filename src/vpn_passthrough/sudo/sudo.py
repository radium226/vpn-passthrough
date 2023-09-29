from types import EllipsisType
from typing import Callable, Any
from subprocess import run

import dill


def sudo(user: str | EllipsisType = ...):
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
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
            process = run(command, input=input_bytes, capture_output=True)
            output_bytes = process.stdout
            output_payload = dill.loads(output_bytes)
            return output_payload

        return closure
    return decorator