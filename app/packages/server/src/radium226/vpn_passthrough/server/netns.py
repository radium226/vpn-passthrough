import asyncio
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from loguru import logger

_TUNNEL_NAME_RE = re.compile(r'^[a-zA-Z0-9_-]{1,64}$')


class Namespace:
    def __init__(self, name: str, base_folder_path: Path) -> None:
        self._name = name
        self._base_folder_path = base_folder_path
        self._pid: int | None = None

    @property
    def name(self) -> str:
        return self._name

    @property
    def pid(self) -> int:
        if self._pid is None:
            self._pid = int((self._base_folder_path / self._name / "pid").read_text().strip())
        return self._pid

    @property
    def directory(self) -> Path:
        return self._base_folder_path / self._name

    def enter(self) -> None:
        """Enter mount + net namespaces. Safe to use as preexec_fn."""
        for ns_type, flag in [("mnt", os.CLONE_NEWNS), ("net", os.CLONE_NEWNET)]:
            fd = os.open(f"/proc/{self.pid}/ns/{ns_type}", os.O_RDONLY | os.O_CLOEXEC)
            os.setns(fd, flag)
            os.close(fd)

    @staticmethod
    @asynccontextmanager
    async def create(name: str, *, base_folder_path: Path) -> AsyncIterator["Namespace"]:
        if not _TUNNEL_NAME_RE.match(name):
            raise ValueError(f"Invalid tunnel name: {name!r} (must match {_TUNNEL_NAME_RE.pattern})")
        ns_dir = base_folder_path / name
        ns_dir.mkdir(parents=True, exist_ok=True)

        proc = await asyncio.create_subprocess_exec(
            "unshare", 
                "--net", 
                "--mount", 
                "--user",
                "--map-user=1000",
                "--map-group=1000",
                "--propagation", "private",
            "tail", "-f", "/dev/null",
        )
        (ns_dir / "pid").write_text(str(proc.pid))

        try:
            yield Namespace(name, base_folder_path)
        finally:
            proc.terminate()
            await proc.wait()
            (ns_dir / "pid").unlink(missing_ok=True)
            try:
                ns_dir.rmdir()
            except OSError:
                logger.warning("Failed to remove namespace directory {}", ns_dir)
