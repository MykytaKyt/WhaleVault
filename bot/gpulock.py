"""One GPU user at a time across processes (the bot and the web API are separate processes).

An asyncio.Lock orders users inside a process; an flock on data/gpu.lock orders the processes.
"""
import asyncio
import fcntl
import os
from pathlib import Path


class GpuLock:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._local = asyncio.Lock()
        self._fd: int | None = None

    def _acquire_file(self) -> None:
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o666)
        fcntl.flock(fd, fcntl.LOCK_EX)
        self._fd = fd

    async def __aenter__(self):
        await self._local.acquire()
        try:
            await asyncio.to_thread(self._acquire_file)
        except BaseException:
            self._local.release()
            raise
        return self

    async def __aexit__(self, *exc):
        fd, self._fd = self._fd, None
        if fd is not None:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
        self._local.release()
        return False

    def locked(self) -> bool:
        """True if this process or another one is using the GPU right now."""
        if self._local.locked():
            return True
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o666)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(fd, fcntl.LOCK_UN)
            return False
        except BlockingIOError:
            return True
        finally:
            os.close(fd)
