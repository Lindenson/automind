"""Delete chats (spec 003 US4: FR-027..FR-030).

Cancel the running or waiting turn first, then remove every chat-scoped record and the saved
conversation state; shared knowledge about cars stays. The caller passes the store and the
checkpoint deletion (composition root), so this module depends on ports only.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable
from typing import Any, Protocol


class ChatStore(Protocol):
    async def delete(self, chat_id: str) -> dict[str, int]: ...


class TurnRunner(Protocol):
    async def cancel(self, chat_id: str) -> bool: ...

    def is_running(self, chat_id: str) -> bool: ...


async def delete_chats(
    ids: Iterable[str],
    runner: TurnRunner,
    store: ChatStore,
    delete_thread: Callable[[str], Awaitable[Any]],
    *,
    wait_s: float = 5.0,
) -> tuple[list[str], dict[str, int]]:
    deleted: list[str] = []
    totals: dict[str, int] = {}
    for chat_id in dict.fromkeys(ids):
        await runner.cancel(chat_id)
        for _ in range(int(wait_s / 0.1)):
            if not runner.is_running(chat_id):
                break
            await asyncio.sleep(0.1)
        counts = await store.delete(chat_id)
        await delete_thread(chat_id)
        if counts:
            deleted.append(chat_id)
            for k, n in counts.items():
                totals[k] = totals.get(k, 0) + n
    return deleted, totals
