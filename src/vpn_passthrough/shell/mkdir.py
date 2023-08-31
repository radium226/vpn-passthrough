from pathlib import Path

from .run import run


def mkdir(folder_path: Path, *, sudo: bool=False):
    run(["mkdir", "-p", str(folder_path)], sudo=sudo)