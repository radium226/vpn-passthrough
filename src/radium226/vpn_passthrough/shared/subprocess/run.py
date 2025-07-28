from typing import Callable, Any
from asyncio.subprocess import create_subprocess_exec, PIPE
from asyncio import StreamReader, TaskGroup

from loguru import logger



async def run(command: list[str], check: bool = False, preexec_fn: Callable[[], Any] | None = None) -> int:
    process = await create_subprocess_exec(
        *command,
        stdout=PIPE, 
        stderr=PIPE,
        preexec_fn=preexec_fn,
    )

    async def log_io(stream_reader: StreamReader | None) -> None:
        if stream_reader is not None: 
            with logger.contextualize(command=" ".join(command)):
                while True:
                    line = await stream_reader.readline()
                    if not line:
                        break
                    logger.debug(line.decode().strip())

    async with TaskGroup() as tg:
        tg.create_task(log_io(process.stdout))
        tg.create_task(log_io(process.stderr))
        wait_task = tg.create_task(process.wait())
    
    exit_code = wait_task.result()
    if check and exit_code != 0:
        raise RuntimeError(f"Command '{' '.join(command)}' failed with exit code {exit_code}")

    return exit_code
