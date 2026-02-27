import asyncio
from collections.abc import Callable
from typing import Any

from loguru import logger


async def run(command: list[str], check: bool = False, preexec_fn: Callable[[], Any] | None = None) -> int:
    logger.debug("Running command: {}", " ".join(command))
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        preexec_fn=preexec_fn,
    )

    assert process.stdout is not None
    assert process.stderr is not None

    async def log_stream(stream: asyncio.StreamReader) -> None:
        async for line in stream:
            logger.debug("{}", line.decode().rstrip())

    await asyncio.gather(
        log_stream(process.stdout),
        log_stream(process.stderr),
    )

    await process.wait()

    if check and process.returncode != 0:
        raise RuntimeError(f"Command {command!r} failed with exit code {process.returncode}")

    return process.returncode or 0
