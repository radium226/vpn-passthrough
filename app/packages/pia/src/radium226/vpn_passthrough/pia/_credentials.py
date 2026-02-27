import os
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from ._models import Auth


@asynccontextmanager
async def credentials_file(auth: Auth) -> AsyncIterator[Path]:
    """Write a two-line OpenVPN credentials file and remove it on exit."""
    fd, raw = tempfile.mkstemp(suffix=".txt")
    path = Path(raw)
    try:
        os.fchmod(fd, 0o600)
        os.write(fd, f"{auth.user}\n{auth.password}\n".encode())
        os.close(fd)
        yield path
    finally:
        path.unlink(missing_ok=True)
