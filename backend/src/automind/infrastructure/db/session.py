"""Async engine and session factory, plus small chat-history helpers."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from automind.config import settings

from .models import ChatMessage, uid

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _engine, _sessionmaker
    if _sessionmaker is None:
        _engine = create_async_engine(settings().database_url, pool_pre_ping=True)
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _sessionmaker


async def init_db() -> None:
    """Bring the schema to the latest Alembic revision (replaces the demo's create_all)."""
    from .migrate import upgrade_head

    sessionmaker()
    await upgrade_head()


async def chat_history(chat_id: str) -> list[ChatMessage]:
    async with sessionmaker()() as s:
        rows = await s.execute(
            select(ChatMessage).where(ChatMessage.chat_id == chat_id).order_by(ChatMessage.created_at)
        )
        return list(rows.scalars())


async def save_message(
    chat_id: str, role: str, text: str, blocks: list | None = None, message_id: str | None = None
) -> ChatMessage:
    async with sessionmaker()() as s:
        m = ChatMessage(id=message_id or uid(), chat_id=chat_id, role=role, text=text, blocks=blocks or [])
        s.add(m)
        await s.commit()
        return m
