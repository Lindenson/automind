"""Event bus for chat turns (research R13).

Every server→client message is persisted in `turn_events` with a monotonic per-chat `seq`, then
fanned out to the chat's live WebSocket subscribers. A reconnecting client sends `hello{last_seq}`
and receives everything after it, so no progress is lost on reload.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

from automind.chat.infrastructure.persistence.repositories import EventRepo


class EventBus:
    def __init__(self, repo: EventRepo | None = None) -> None:
        self.repo = repo or EventRepo()
        self._subs: dict[str, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)

    async def publish(self, chat_id: str, turn_id: str | None, type_: str, payload: dict[str, Any]) -> int:
        seq = await self.repo.append(chat_id, turn_id, type_, payload)
        msg = {"type": type_, "seq": seq, "turn_id": turn_id, **payload}
        for q in list(self._subs.get(chat_id, ())):
            q.put_nowait(msg)
        return seq

    def subscribe(self, chat_id: str) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._subs[chat_id].add(q)
        return q

    def unsubscribe(self, chat_id: str, q: asyncio.Queue[dict[str, Any]]) -> None:
        self._subs.get(chat_id, set()).discard(q)

    async def current(self, chat_id: str, turn_id: str, type_: str) -> dict[str, Any] | None:
        """The turn's latest event of a type, without its seq: re-sent after a reconnect so a client that
        already saw it (and reloaded) gets the open question or the current status again."""
        from automind.chat.infrastructure.persistence.repositories import latest_event  # noqa: PLC0415

        e = await latest_event(chat_id, turn_id, type_)
        return None if e is None else {"type": e.type, "turn_id": e.turn_id, "resent": True, **e.payload}

    async def replay(self, chat_id: str, after_seq: int) -> list[dict[str, Any]]:
        return [
            {"type": e.type, "seq": e.seq, "turn_id": e.turn_id, **e.payload}
            for e in await self.repo.since(chat_id, after_seq)
        ]
