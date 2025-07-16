from typing import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from loguru import logger
from subprocess import run, Popen
from pathlib import Path
from time import sleep
from tempfile import NamedTemporaryFile
from enum import StrEnum, auto
from contextlib import ExitStack

from .netns import NetNS
from .pia import Region, OPENVPN_PORT, Credentials


OPENVPN_DEV = "tun0"  # Default OpenVPN device, can be overridden by the user


class HookType(StrEnum):
    UP = auto()
    DOWN = auto()


def wait_for_file_to_be_created(file_path: Path, timeout: int = 10) -> None:
    for try_count in range(timeout):
        logger.debug(f"Waiting for file {file_path} to be created...")
        """
        Wait for a file to be created.
        This is a simple utility function to ensure that the OpenVPN script has been executed.
        """
        if file_path.exists():
            logger.debug(f"File {file_path} has been created.")
            return
        if try_count >= timeout:
            raise TimeoutError(f"Timeout waiting for {file_path} to be created")
        # Sleep briefly to avoid busy-waiting
        sleep(1)  # Adjust the sleep duration as needed


def wait_for_file_to_be_deleted(file_path: Path, timeout: int = 10) -> None:
    for try_count in range(timeout):
        logger.debug(f"Waiting for file {file_path} to be deleted...")
        """
        Wait for a file to be created.
        This is a simple utility function to ensure that the OpenVPN script has been executed.
        """
        if not file_path.exists():
            logger.debug(f"File {file_path} has been deleted.")
            return
        if try_count >= timeout:
            raise TimeoutError(f"Timeout waiting for {file_path} to be created")
        # Sleep briefly to avoid busy-waiting
        sleep(1)  # Adjust the sleep duration as needed


@contextmanager
def create_openvpn_script(hook_type: HookType, netns: NetNS) -> Generator[Path, None, None]:
    with NamedTemporaryFile(delete=False, mode='w', suffix='') as f:
        f.write(
            (Path(__file__).parent / "openvpn-script.sh")
                .read_text()
                .replace("%NETNS_NAME%", netns.name)
                .replace("%HOOK_TYPE%", hook_type.value)
        )
        f.flush()
        f.close()
        run(["chmod", "755", f.name], check=True)
        script_file_path = Path(f.name)
        logger.debug("script_file_path={script_file_path}", script_file_path=script_file_path)
        yield script_file_path


@contextmanager
def start_openvpn(
    netns: NetNS,
    pia_credentials: Credentials,
    pia_region: Region,
) -> Generator[None, None, None]:
    exit_stack = ExitStack()

    try:
        pia_credentials_file_path = exit_stack.enter_context(pia_credentials.to_file())
        openvpn_up_script_file_path = exit_stack.enter_context(create_openvpn_script(HookType.UP, netns))
        openvpn_down_script_file_path = exit_stack.enter_context(create_openvpn_script(HookType.DOWN, netns))
        openvpn_remote = pia_region.servers.ovpnudp[0].ip
        ip_command = ["ip", "netns", "exec", netns.name]
        openvpn_command = [
            "openvpn",
            # "--verb", str(6),
            "--client",
            "--dev", OPENVPN_DEV,
            "--proto", "udp",
            "--resolv-retry", "infinite",
            "--nobind", 
            "--persist-key",
            "--persist-tun", 
            "--cipher", "AES-256-CBC",
            "--data-ciphers-fallback", "AES-256-CBC",
            "--auth", "sha1",
            "--tls-client", 
            "--remote-cert-tls", "server",
            "--auth-user-pass", 
            "--compress",
            "--reneg-sec", "0",
            # "--crl-verify", "/etc/vpn-passthrough/ca.rsa.2048.crl",
            "--ca", str(Path(__file__).parent / "ca.rsa.2048.crt"),
            "--disable-occ", 
            "--errors-to-stderr", 
            "--pull-filter", "ignore", "route-ipv6",
            "--pull-filter", "ignore", "ifconfig-ipv6",
            "--remote", openvpn_remote, 
            "--port", str(OPENVPN_PORT),
            "--auth-user-pass", str(pia_credentials_file_path),
            "--auth-nocache",
            "--script-security", "2",
            "--up", str(openvpn_up_script_file_path),
            "--down", str(openvpn_down_script_file_path),
        ]

        command = ip_command + openvpn_command
        logger.debug("command={command}", command=command)
        process = Popen(command)
        def terminate_process():
            process.terminate()
            wait_for_file_to_be_deleted(Path(f"/tmp/openvpn-{netns.name}.ready")) 
            process.wait()

        exit_stack.callback(terminate_process)
        wait_for_file_to_be_created(Path(f"/tmp/openvpn-{netns.name}.ready"))
        yield
    finally:
        logger.debug("Stopping OpenVPN...")
        exit_stack.close()