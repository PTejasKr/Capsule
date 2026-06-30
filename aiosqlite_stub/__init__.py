import sqlite3
import asyncio
from typing import Any

# Simple stub mimicking aiosqlite's async API using the built‑in sqlite3 module.

class Row(sqlite3.Row):
    """Alias for compatibility with aiosqlite.Row."""
    pass

class _CursorWrapper:
    def __init__(self, connection: sqlite3.Connection, sql: str, params: tuple):
        self._conn = connection
        self._sql = sql
        self._params = params
        self._cur = None
        self.rowcount = -1

    async def __aenter__(self):
        def _exec():
            self._cur = self._conn.execute(self._sql, self._params)
            self.rowcount = self._cur.rowcount
            return self
        await asyncio.to_thread(_exec)
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def __await__(self):
        return self.__aenter__().__await__()

    async def fetchone(self) -> Any:
        return await asyncio.to_thread(self._cur.fetchone)

    async def fetchall(self) -> list[Any]:
        return await asyncio.to_thread(self._cur.fetchall)

    @property
    def lastrowid(self):
        return self._cur.lastrowid if self._cur else None

class _ConnectionWrapper:
    def __init__(self, path: str):
        # ``check_same_thread=False`` allows usage from different threads.
        self._conn = sqlite3.connect(path, check_same_thread=False)
        # Default row factory; callers may override.
        self.row_factory = sqlite3.Row
        self._conn.row_factory = self.row_factory

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()
        return False

    def execute(self, sql: str, params: tuple = ()):
        """Execute a statement and return a cursor wrapper.
        The returned object supports ``async with`` and ``fetchone``/``fetchall``.
        """
        # Set current connection row_factory to match connection setting
        self._conn.row_factory = self.row_factory
        return _CursorWrapper(self._conn, sql, params)

    async def commit(self):
        await asyncio.to_thread(self._conn.commit)

    async def close(self):
        await asyncio.to_thread(self._conn.close)

    # ``executemany`` and other helpers can be added if needed.

def connect(path: str) -> _ConnectionWrapper:
    """Factory function mirroring ``aiosqlite.connect``.
    Returns an async context manager that yields a connection compatible with the
    subset of the real API used in this project.
    """
    return _ConnectionWrapper(path)

__all__ = ["connect", "Row"]
