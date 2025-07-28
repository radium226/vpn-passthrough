from asyncio.subprocess import Process



class Execution():

    _process: Process
    _command: list[str]

    def __init__(self, process: Process, command: list[str]):
        self._process = process
        self._command = command


    @property
    def command(self) -> list[str]:
        return self._command
    
    @property
    def process(self) -> Process:
        return self._process
    
    @property
    def name(self) -> str:
        return self._command[0] if self._command else "no_name"
    

    async def send_signal(self, signal: int) -> None:
        # Implementation for sending a signal to the process
        pass

    async def wait_for(self) -> int:
        # Wait for the process to complete and return the exit code
        return await self._process.wait()