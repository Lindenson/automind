"""LangGraph Postgres checkpointer (research R2): one persistent thread per chat.

The checkpointer owns its own tables (checkpoints, checkpoint_blobs, checkpoint_writes,
checkpoint_migrations); Alembic never touches them.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import parse_qs, urlparse

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from automind.config import settings


def psycopg_conninfo(database_url: str) -> str:
    """Convert `postgresql+asyncpg://user:pw@host:port/db?host=/socket/dir` to a libpq conninfo string."""
    u = urlparse(database_url)
    q = parse_qs(u.query)
    parts: dict[str, str] = {"dbname": (u.path or "/postgres").lstrip("/") or "postgres"}
    if u.username:
        parts["user"] = u.username
    if u.password:
        parts["password"] = u.password
    host = q.get("host", [u.hostname or ""])[0]
    if host:
        parts["host"] = host
    if u.port:
        parts["port"] = str(u.port)
    return " ".join(f"{k}={v}" for k, v in parts.items())


@asynccontextmanager
async def checkpointer(database_url: str | None = None, max_size: int = 10) -> AsyncIterator[AsyncPostgresSaver]:
    """Open a pooled AsyncPostgresSaver and create its tables if needed."""
    pool = AsyncConnectionPool(
        conninfo=psycopg_conninfo(database_url or settings().database_url),
        max_size=max_size,
        open=False,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    )
    await pool.open()
    try:
        saver = AsyncPostgresSaver(pool)  # type: ignore[arg-type]
        await saver.setup()
        yield saver
    finally:
        await pool.close()
