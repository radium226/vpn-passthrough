import pytest
from typing import Generator
import os
from subprocess import Popen, run, STDOUT
from loguru import logger
from dataclasses import dataclass
from time import sleep
from pathlib import Path



@pytest.fixture(scope="session")
def daemon() -> Generator[None, None, None]:
    logger.info("Starting vpn-passthrough daemon...")
    process = Popen([
        "sudo",
        "--preserve-env=PIA_USER,PIA_PASS",
        "./.venv/bin/python",
        "-m", "radium226.vpn_passthrough.server",
        "--bus-scope", "system",
    ])
    sleep(1)  # Give the daemon some time to start
    logger.info("Started! (pid={pid})", pid=process.pid)
    try:
        yield
    finally:
        logger.info("Stopping vpn-passthrough daemon...")
        process.terminate()
        process.wait()
        logger.info("Stopped! ")



@dataclass
class CLIOutcome():

    stdout: str
    stderr: str
    exit_code: int



class CLI():

    def __call__(self, command: list[str]) -> CLIOutcome:
        result = run(
            ["vpn-passthrough", "--bus-scope=system"] + command, 
            check=False, 
            text=True, 
            capture_output=True,
            env={
                **os.environ,
                "FOO": "bar",
            },
        )
        return CLIOutcome(stdout=result.stdout, stderr=result.stderr, exit_code=result.returncode)



@pytest.fixture(scope="session")
def cli() -> CLI:
    return CLI()


def e2e():
    def decorator(func):
        func = pytest.mark.usefixtures("daemon")(func)
        func = pytest.mark.e2e(func)
        return func
    return decorator



@e2e()
def test_list_regions(cli: CLI) -> None:
    outcome = cli(["list-regions"])
    stderr = outcome.stderr
    assert stderr == "", "Expected no error output, got: {stderr}"

    stdout = outcome.stdout
    assert "france" in stdout or "us" in stdout or "uk" in stdout, "Expected at least one region to be listed"



@e2e()
@pytest.mark.parametrize(
    "command, expected_stdout, expected_exit_code",
    [
        (["id", "-u"], str(os.getuid()), 0),
        (["pwd"], str(Path.cwd()), 0),
        (["sh", "-c", "echo \"${FOO}\""], "bar", 0),
        (["ip", "netns", "identify"], "e2e", 0),
        (["sh", "-c", "sleep 30 ; echo 'FOOBAR'"], "FOOBAR", 0),
        (["sh", "-c", "for i in 1 2 3 4 5; do echo -en \"${i}\" ; sleep 1; done ; exit 42"], "12345", 42),
    ]
)
def test_execute(cli: CLI, command, expected_stdout, expected_exit_code) -> None:
    outcome = cli(["execute", "--name=e2e", "--"] + command)
    # assert outcome.stderr == "", "Expected no error output, got: {outcome.stderr}"

    stdout = outcome.stdout
    assert expected_stdout in stdout, f"Expected output to contain '{expected_stdout}', got: {stdout}"

    exit_code = outcome.exit_code
    assert exit_code == expected_exit_code, f"Expected exit code {expected_exit_code}, got: {exit_code}"