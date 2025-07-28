from typing import AsyncGenerator, Self
from contextlib import asynccontextmanager, AsyncExitStack
from dataclasses import dataclass, field
from pathlib import Path
from loguru import logger

from asyncio.subprocess import create_subprocess_exec, Process
from .netns import NetNS
from tempfile import mkdtemp
from textwrap import dedent
from select import select

import os



@dataclass
class OpenVPNAuth():

    user: str
    password: str


def _load_default_certificate() -> bytes:
    file_path = Path(__file__).parent / "ca.rsa.2048.crt"
    if not file_path.exists():
        raise FileNotFoundError(f"Certificate file not found: {file_path}")
    return file_path.read_bytes()


@dataclass
class OpenVPNConfig():

    port: int
    remote: str
    auth: OpenVPNAuth
    proto: str = "udp"
    dev_name: str = "tun0"
    verbosity: int = 1
    certificate: bytes = field(default_factory=_load_default_certificate)


class OpenVPN:

    _process: Process

    _gateway_ip: str | None = None

    def __init__(self, process: Process, gateway_ip: str | None = None):
        self._process = process
        self._gateway_ip = gateway_ip

    @property
    def gatway_ip(self) -> str | None:
        return self._gateway_ip


    @classmethod
    @asynccontextmanager
    async def start(cls, config: OpenVPNConfig, netns: NetNS | None = None) -> AsyncGenerator[Self, None]:
        exit_stack = AsyncExitStack()
        try:
            temp_folder_path = Path(mkdtemp(prefix="openvpn-"))
            # exit_stack.callback(shutil.rmtree, temp_folder_path)
            logger.debug(f"{temp_folder_path=}")

            ca_file_path = temp_folder_path / "ca.rsa.2048.crt"
            ca_file_path.write_bytes(config.certificate)

            auth_file_path = temp_folder_path / "auth.txt"
            auth_file_path.write_text(f"{config.auth.user}\n{config.auth.password}")

            read_fd, write_fd = os.pipe()
            logger.debug(f"{read_fd=}, {write_fd=}")
            script_args = []
            for script_type in ["up", "down"]:
                script = dedent("""\
                    #!/bin/sh
                    echo "{script_type} ${{@}}" >&{write_fd}
                """).format(script_type=script_type, write_fd=write_fd)
                script_file_path = temp_folder_path / script_type
                script_file_path.write_text(script)
                os.chmod(script_file_path, 755)
                script_args += [
                    f"--{script_type}",
                    str(script_file_path),
                ]

            def preexec_fn() -> None:
                if netns:
                    netns.enter()
                else:
                    logger.debug("No NetNS provided, not switching namespaces.")

            logger.debug(f"{auth_file_path=}")
            command = [
                "openvpn",
                    "--client",
                    "--dev", config.dev_name,
                    "--verb", str(3),
                    "--proto", config.proto,
                    "--resolv-retry", "infinite",
                    "--nobind",
                    "--persist-key",
                    "--persist-tun",
                    "--cipher", "AES-256-CBC",
                    "--data-ciphers-fallback", "AES-256-CBC",
                    "--auth", "sha1",
                    "--tls-client",
                    "--remote-cert-tls", "server",
                    "--auth-user-pass", str(auth_file_path),
                    "--compress",
                    "--reneg-sec", "0",
                    "--ca", str(ca_file_path),
                    "--disable-occ",
                    "--errors-to-stderr",
                    "--pull-filter", "ignore", "route-ipv6",
                    "--pull-filter", "ignore", "ifconfig-ipv6",
                    "--remote", config.remote,
                    "--port", str(config.port),
                    "--auth-nocache",
                    "--script-security", "2",
                    *script_args,
            ]
            logger.debug(f"{command=}")

            logger.debug("Starting OpenVPN... ")
            process = await create_subprocess_exec(
                *command,
                preexec_fn=preexec_fn,
                pass_fds=[write_fd],
            )
            logger.debug("OpenVPN started! (pid={pid})", pid=process.pid)

            def wait_for_script(script_type: str) -> str:
                logger.debug(f"Waiting for OpenVPN to be {script_type}...")
                _, _, _ = select([read_fd], [], [])
                line = os.read(read_fd, 1024).decode("utf-8").strip()
                logger.debug("line={line}", line=line)
                received_script_type, reminder = line.split(maxsplit=1)
                assert script_type == received_script_type
                logger.debug(f"OpenVPN is {script_type}! ")
                return reminder

            config_line = wait_for_script("up")
            logger.info(f"config_line={config_line}")
            exit_stack.callback(wait_for_script, "down")

            async def terminate_and_wait_for_process() -> None:
                process.terminate()
                await process.wait()
                logger.debug("OpenVPN process terminated and waited for.")

            exit_stack.push_async_callback(terminate_and_wait_for_process)

            yield cls(process)
        except Exception as e:
            logger.error(f"Error starting OpenVPN: {e}")
            raise
        finally:
            await exit_stack.aclose()



    async def wait_for(self) -> None:
        exit_code = self._process.wait()
        logger.debug(f"OpenVPN process exited with code {exit_code}")