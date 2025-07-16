from typing import Generator
from pathlib import Path
from contextlib import contextmanager
from os import environ
from subprocess import run

from .netns import NetNS


@contextmanager
def bind_pipewire(
    netns: NetNS,
) -> Generator[None, None, None]:
    source_file_path = Path(environ["XDG_RUNTIME_DIR"]) / "pipewire-0"
    target_file_path = Path("/var/run/netns") / netns.name / source_file_path
    run([
        "mount",
        "--bind",
        str(source_file_path),
        str(target_file_path),
        ], 
        check=True,
    )
    try:
        yield
    finally:
        run([
            "umount",
            str(target_file_path),
        ], check=True)

