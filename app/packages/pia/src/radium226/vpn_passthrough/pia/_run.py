import asyncio
from collections.abc import Callable
from typing import Any

from loguru import logger


async def run(command: list[str], *, check: bool = False, preexec_fn: Callable[[], Any] | None = None) -> tuple[int, bytes]:
    logger.debug("Running: {}", " ".join(command))
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        preexec_fn=preexec_fn,
    )
    stdout, stderr = await process.communicate()
    for line in stderr.decode().splitlines():
        logger.debug("[stderr] {}", line)
    if check and process.returncode != 0:
        raise RuntimeError(
            f"Command {command!r} failed with exit code {process.returncode}"
        )
    return process.returncode or 0, stdout
