"""Spec 013 T033: each turn's understanding in `turn_understanding` — a turn written again replaces its row, the
chat's latest open question is read back, rows older than 90 days are pruned and a deleted chat takes its rows."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import update

from automind.chat.domain.understanding.intent import Override
from automind.chat.domain.understanding.record import Dropped, UnderstandingRecord
from automind.chat.infrastructure.persistence.repositories import ChatRepo
from automind.chat.infrastructure.persistence.understanding import KEEP_DAYS, UnderstandingRepo
from automind.chat.infrastructure.retention import prune_understanding
from automind.shared.infrastructure import db
from automind.shared.infrastructure.db.models import TurnUnderstandingRow
from automind.shared.infrastructure.db.session import sessionmaker


@pytest.fixture
async def repo() -> UnderstandingRepo:
    await db.init_db()
    return UnderstandingRepo()


def _record(chat: str, turn: str, question: str | None = "q-1", refused: str | None = None) -> UnderstandingRecord:
    return UnderstandingRecord(
        chat_id=chat, turn_id=turn, source="text", input={"text": "да, но дизель", "question": None},
        open_question_id=question, model="gemini-3.1-flash-lite", prompt_version="understander@v1", latency_ms=812,
        model_raw={"language": "ru"}, refused=refused,
        rejected=(Dropped(check="numbers_in_message", field="set_budget.max_eur", why="50000 is not written"),),
        overrides=(Override(rule="stale_pending", field="answer_to_pending", before={"kind": "yes"}, why="old"),),
        intent=None if refused else {"source": "text", "language": "ru"}, old_reading={"language": "ru"},
    )  # fmt: skip


async def test_a_turn_reads_back_and_a_retry_replaces_its_row(repo: UnderstandingRepo) -> None:
    chat, turn = str(uuid.uuid4()), str(uuid.uuid4())
    await repo.record(_record(chat, turn))
    await repo.record(_record(chat, turn, refused="RuntimeError: provider down"))
    back = await repo.for_turn(turn)
    assert back == _record(chat, turn, refused="RuntimeError: provider down")
    assert await repo.for_turn(str(uuid.uuid4())) is None


async def test_the_chats_latest_open_question(repo: UnderstandingRepo) -> None:
    chat = str(uuid.uuid4())
    assert await repo.last_question(chat) is None
    await repo.record(_record(chat, str(uuid.uuid4()), "q-1"))
    await repo.record(_record(chat, str(uuid.uuid4()), "q-2"))
    assert await repo.last_question(chat) == "q-2"


async def test_rows_older_than_90_days_are_pruned_and_a_deleted_chat_takes_its_rows(repo: UnderstandingRepo) -> None:
    chat, old, new = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    await repo.record(_record(chat, old))
    await repo.record(_record(chat, new))
    async with sessionmaker()() as s:
        long_ago = datetime.now(UTC) - timedelta(days=KEEP_DAYS + 1)
        q = update(TurnUnderstandingRow).where(TurnUnderstandingRow.turn_id == old).values(created_at=long_ago)
        await s.execute(q)
        await s.commit()
    assert await prune_understanding(repo) >= 1
    assert await repo.for_turn(old) is None and await repo.for_turn(new) is not None
    counts = await ChatRepo().delete(chat)
    assert counts["turn_understanding"] == 1 and await repo.for_turn(new) is None
