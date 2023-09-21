from pathlib import Path
from typing import Callable
from enum import StrEnum, auto
from subprocess import run


class Source(StrEnum):

    DOC = auto()

    FILE = auto()


def nftables(debug: bool = False, source: Source = ...):
    def decorator(func: Callable[..., None]) -> Callable[..., None]:
        def closure(*args, **kwargs):
            func_name = func.__name__
            func_doc = func.__doc__

            check = kwargs.get("check", False)

            script_file_path = Path(__file__).parent / "scripts" / f"{func_name}.nft"
            
            script: str = ...

            match source:
                case Source.DOC:
                    if not func_doc:
                        raise Exception("The doc is undefined! ")
                    
                    script = func_doc

                case Source.FILE:
                    if not script_file_path.exists():
                        raise Exception("The script file does not exist! ")
                    
                    with script_file_path.open("r") as script_stream:
                        script = script_stream.read()

                case _:
                    if script_file_path.exists():
                        with script_file_path.open("r") as script_stream:
                            script = script_stream.read()
                    else:
                        script = func_doc

            if script is ...:
                raise Exception("Unable to infer the script!")

            if debug:
                message = script.format(**kwargs)
                run(["echo", message], check=True)
            else:
                nft_command = ["sudo", "nft", "-f", "-"] + (["-c"] if check else [])
                run(nft_command, input=script, check=True, text=True)

        return closure
    return decorator