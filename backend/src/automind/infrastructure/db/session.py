"""Async engine and session factory, plus small chat-history helpers."""

from __future__ import annotations

from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from automind.config import settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


NUL = "\x00"


def _clean(v: Any) -> Any:
    """Postgres text and jsonb reject the NUL character; web pages sometimes contain it (chat 2026-11-06, Deepal S09
    vs Li L9: one page crashed the whole turn). It carries no meaning, so it is removed from every string bound to a
    statement."""
    if isinstance(v, str):
        return v.replace(NUL, "").replace("\\u0000", "") if NUL in v or "\\u0000" in v else v
    return v


def strip_nul(conn: Any, cursor: Any, statement: str, params: Any, context: Any, executemany: bool) -> Any:
    if isinstance(params, dict):
        params = {k: _clean(v) for k, v in params.items()}
    elif isinstance(params, list | tuple):
        params = type(params)(
            (type(p)(_clean(x) for x in p) if isinstance(p, list | tuple)
             else {k: _clean(x) for k, x in p.items()} if isinstance(p, dict) else _clean(p))
            for p in params
        )  # fmt: skip
    return statement, params


def sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _engine, _sessionmaker
    if _sessionmaker is None:
        _engine = create_async_engine(settings().database_url, pool_pre_ping=True)
        event.listen(_engine.sync_engine, "before_cursor_execute", strip_nul, retval=True)
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _sessionmaker


async def init_db() -> None:
    """Bring the schema to the latest Alembic revision (replaces the demo's create_all)."""
    from .migrate import upgrade_head

    sessionmaker()
    await upgrade_head()
