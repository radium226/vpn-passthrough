from subprocess import Popen
from getpass import getuser
from pathlib import Path
import os
from signal import SIGTERM
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..network_namespace import NetworkNamespace

# def tee(content, file_path, append=False, sudo=False):
#     tee_process = execute(["tee"] + (["-a"] if append else []) + [str(file_path)], sudo=sudo, background=True, stdin=sp.PIPE)
#     tee_process.stdin.write(content)
#     tee_process.stdin.close()
#     tee_process.wait()


# def kill(process, signal=SIGTERM, sudo=False, group=True):
#     pid = process.pid
#     if group:
#         pgid = os.getpgid(process.pid)
#         execute(["kill", f"-{signal}", f"-{str(pgid)}"], sudo=sudo)
#     else:
#         execute(["kill", f"-{signal}", str(pid)], sudo=sudo)


def run(command: list[str], *, success_exit_codes: list[int]=[0], sudo: bool=False, network_namespace: NetworkNamespace | None=None, background=False, stdin=None, stdout=None, in_folder=None):
    before_command = []
    if network_namespace:
        user = getuser()
        before_command = ["sudo", "-E", "ip", "netns", "exec", network_namespace.name, "sudo", "-E", "-u", user]

    if sudo:
        before_command = before_command + ["sudo", "-E"]

    process = Popen(before_command + command, stdin=stdin, stdout=stdout, start_new_session=True, cwd=str(in_folder) if in_folder else None)
    if background:
        return process
    else:
        process.wait()
        exit_code = process.returncode
        if exit_code not in success_exit_codes:
            raise Exception(f"The {before_command + command} process failed! ")
