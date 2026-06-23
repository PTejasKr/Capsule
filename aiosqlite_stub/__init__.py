import sqlite3
import asyncio
from typing import Any

# Simple stub mimicking aiosqlite's async API using the built‑in sqlite3 module.

class Row(sqlite3.Row):
    """Alias for compatibility with aiosqlite.Row."""
    pass

class _CursorWrapper:
    def __init__(self, cursor: sqlite3.Cursor):
        self._cur = cursor
        self.rowcount = cursor.rowcount

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        # sqlite3 cursors are closed automatically when connection closes
        return False

    async def fetchone(self) -> Any:
        return await asyncio.to_thread(self._cur.fetchone)

    async def fetchall(self) -> list[Any]:
        return await asyncio.to_thread(self._cur.fetchall)

    # aiosqlite exposes ``fetch`` as an alias for ``fetchone``; not needed here.

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

    async def execute(self, sql: str, params: tuple = ()):  # noqa: D401
        """Execute a statement and return a cursor wrapper.
        The returned object supports ``async with`` and ``fetchone``/``fetchall``.
        """
        def _exec():
            cur = self._conn.execute(sql, params)
            return cur
        cursor = await asyncio.to_thread(_exec)
        return _CursorWrapper(cursor)

    async def commit(self):
        await asyncio.to_thread(self._conn.commit)

    async def close(self):
        await asyncio.to_thread(self._conn.close)

    # ``executemany`` and other helpers can be added if needed.

async def connect(path: str) -> _ConnectionWrapper:
    """Factory function mirroring ``aiosqlite.connect``.
    Returns an async context manager that yields a connection compatible with the
    subset of the real API used in this project.
    """
    return _ConnectionWrapper(path)

__all__ = ["connect", "Row"]
