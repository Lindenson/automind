"""Each turn's understanding (spec 013 T033): `turn_understanding` keyed by `turn_id`. Implements
`application.ports.UnderstandingLog`; every method raises `StoreUnavailable` when the database fails
(`store_errors`). `prune` is the daily retention step (90 days, owner 2026-11-27)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from automind.chat.domain.understanding.record import UnderstandingRecord
from automind.chat.infrastructure.persistence.errors import store_errors
from automind.shared.infrastructure.db.models import TurnUnderstandingRow
from automind.shared.infrastructure.db.session import sessionmaker

KEEP_DAYS = 90


class UnderstandingRepo:
    """Implements `UnderstandingLog` over `turn_understanding`."""

    @store_errors
    async def record(self, rec: UnderstandingRecord) -> None:
        """Upsert the turn's row by `turn_id`."""
        values = rec.model_dump(mode="json")
        async with sessionmaker()() as s:
            row = insert(TurnUnderstandingRow).values(**values)
            fields = {k: row.excluded[k] for k in values if k != "turn_id"}
            await s.execute(row.on_conflict_do_update(index_elements=["turn_id"], set_=fields))
            await s.commit()

    @store_errors
    async def for_turn(self, turn_id: str) -> UnderstandingRecord | None:
        """The turn's row as a record."""
        async with sessionmaker()() as s:
            row = await s.get(TurnUnderstandingRow, turn_id)
            return _record(row) if row is not None else None

    @store_errors
    async def last_question(self, chat_id: str) -> str | None:
        """The open question id of the chat's latest row."""
        async with sessionmaker()() as s:
            q = (
                select(TurnUnderstandingRow.open_question_id)
                .where(TurnUnderstandingRow.chat_id == chat_id)
                .order_by(TurnUnderstandingRow.created_at.desc())
                .limit(1)
            )
            return (await s.execute(q)).scalar_one_or_none()

    @store_errors
    async def prune(self, before: datetime) -> int:
        """Delete the rows recorded before `before`; returns how many."""
        async with sessionmaker()() as s:
            old = delete(TurnUnderstandingRow).where(TurnUnderstandingRow.created_at < before)
            deleted = (await s.execute(old.returning(TurnUnderstandingRow.turn_id))).all()
            await s.commit()
            return len(deleted)


def _record(r: TurnUnderstandingRow) -> UnderstandingRecord:
    fields = UnderstandingRecord.model_fields
    return UnderstandingRecord.model_validate({k: getattr(r, k) for k in fields})
