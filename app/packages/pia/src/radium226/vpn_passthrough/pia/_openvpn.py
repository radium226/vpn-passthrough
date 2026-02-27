import asyncio
import os
import stat
import tempfile
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from loguru import logger

_DEFAULT_CA_CERT_PATH = Path(__file__).parent / "ca.rsa.4096.crt"
_CONNECT_TIMEOUT = 60.0


async def _log_stream(stream: asyncio.StreamReader, label: str) -> None:
    while True:
        line = await stream.readline()
        if not line:
            break
        logger.debug("[openvpn {}] {}", label, line.decode().rstrip())


@asynccontextmanager
async def openvpn_connected(
    netns_name: str,
    server_ip: str,
    server_port: int,
    credentials_path: Path,
    *,
    enter_netns: Callable[[], None],
    ca_cert_path: Path = _DEFAULT_CA_CERT_PATH,
) -> AsyncIterator[tuple[str, str, list[str]]]:
    """Start OpenVPN inside the namespace and yield ``(gateway_ip, dns_servers)`` once connected.

    The ``--up`` script pipes the gateway IP then the DNS IPs (one per line,
    terminated by an empty line) so Python can write resolv.conf directly.
    """
    read_fd, write_fd = os.pipe()

    # The --up script:
    #   1. Writes $route_vpn_gateway as the first line.
    #   2. Iterates foreign_option_N env vars and emits each "dhcp-option DNS <ip>"
    #      value as a bare IP line.
    #   3. Writes an empty line to signal end-of-DNS.
    # Python reads all of this, writes resolv.conf, then yields to the caller.
    up_script_fd, up_script_path = tempfile.mkstemp(prefix="openvpn-up-", suffix=".sh")
    os.write(up_script_fd, (
        "#!/bin/sh\n"
        f'printf "%s\\n" "$route_vpn_gateway" >&{write_fd}\n'
        f'printf "%s\\n" "$ifconfig_local" >&{write_fd}\n'
        "i=1\n"
        "while true; do\n"
        '    eval "val=\\$foreign_option_$i"\n'
        '    [ -z "$val" ] && break\n'
        '    case "$val" in\n'
        f'        "dhcp-option DNS "*) printf "%s\\n" "${{val#dhcp-option DNS }}" >&{write_fd} ;;\n'
        "    esac\n"
        "    i=$((i + 1))\n"
        "done\n"
        f'printf "\\n" >&{write_fd}\n'
        f"exec {write_fd}>&-\n"
    ).encode())
    os.fchmod(up_script_fd, stat.S_IRWXU)
    os.close(up_script_fd)

    cmd = [
        "openvpn",
        "--client",
        "--dev", "tun0",
        "--proto", "udp",
        "--remote", server_ip, str(server_port),
        "--cipher", "AES-256-CBC",
        "--data-ciphers-fallback", "AES-256-CBC",
        "--auth", "sha256",
        "--tls-client",
        "--remote-cert-tls", "server",
        "--ca", str(ca_cert_path),
        "--auth-user-pass", str(credentials_path),
        "--auth-nocache",
        "--compress",
        "--reneg-sec", "0",
        "--resolv-retry", "infinite",
        "--nobind",
        "--persist-key",
        "--persist-tun",
        "--disable-occ",
        "--errors-to-stderr",
        "--pull-filter", "ignore", "route-ipv6",
        "--pull-filter", "ignore", "ifconfig-ipv6",
        "--script-security", "2",
        "--up", up_script_path,
    ]

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        preexec_fn=enter_netns,
        pass_fds=(write_fd,),
    )

    os.close(write_fd)

    log_tasks: list[asyncio.Task[None]] = []
    assert process.stdout is not None
    assert process.stderr is not None
    log_tasks.append(asyncio.create_task(_log_stream(process.stdout, "stdout")))
    log_tasks.append(asyncio.create_task(_log_stream(process.stderr, "stderr")))

    try:
        loop = asyncio.get_running_loop()
        reader = asyncio.StreamReader()
        transport, _ = await loop.connect_read_pipe(
            lambda: asyncio.StreamReaderProtocol(reader),
            os.fdopen(read_fd, "rb", closefd=False),
        )

        async def _read_connection_info() -> tuple[str, str, list[str]]:
            data = await reader.readline()
            if not data:
                raise RuntimeError("OpenVPN exited before connecting")
            gateway_ip = data.decode().strip()
            tun_ip = (await reader.readline()).decode().strip()
            dns_servers: list[str] = []
            while True:
                line = (await reader.readline()).decode().strip()
                if not line:
                    break
                dns_servers.append(line)
            return gateway_ip, tun_ip, dns_servers

        try:
            gateway_ip, tun_ip, dns_servers = await asyncio.wait_for(
                _read_connection_info(), timeout=_CONNECT_TIMEOUT
            )
        except TimeoutError:
            raise TimeoutError(
                f"OpenVPN did not connect within {_CONNECT_TIMEOUT}s"
            )
        finally:
            transport.close()
            os.close(read_fd)

        if not dns_servers:
            dns_servers = [gateway_ip]

        logger.info(
            "OpenVPN connected in netns {} (gateway {}, tun_ip {}, dns {})",
            netns_name, gateway_ip, tun_ip, dns_servers,
        )
        yield gateway_ip, tun_ip, dns_servers

    finally:
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=5.0)
            except TimeoutError:
                process.kill()
                await process.wait()
        for task in log_tasks:
            task.cancel()
        await asyncio.gather(*log_tasks, return_exceptions=True)
        os.unlink(up_script_path)
        logger.info("OpenVPN disconnected from netns {}", netns_name)
