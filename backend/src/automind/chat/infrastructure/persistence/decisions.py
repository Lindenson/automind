"""The policy's passes (spec 015 D5): `policy_decisions` keyed `(turn_id, pass_no)` and `policy_configs` by hash.
Implements `application.ports.DecisionLog`; every method raises `StoreUnavailable` when the database fails
(`store_errors`). `prune` is the daily retention step (90 days, spec 015 §H D2)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from automind.chat.domain.decision import DecisionRecord, TrailStep
from automind.chat.infrastructure.persistence.errors import store_errors
from automind.shared.contracts.json import JsonObject
from automind.shared.infrastructure.db.models import PolicyConfigRow, PolicyDecisionRow
from automind.shared.infrastructure.db.session import sessionmaker

KEEP_DAYS = 90  # spec 015 §H D2


class DecisionRepo:
    """Implements `DecisionLog` over `policy_decisions` and `policy_configs`."""

    @store_errors
    async def record(self, rec: DecisionRecord, config: JsonObject) -> None:
        """Upsert the pass by `(turn_id, pass_no)`; insert the config once per hash."""
        values = rec.model_dump(mode="json")
        async with sessionmaker()() as s:
            cfg = insert(PolicyConfigRow).values(config_hash=rec.config_hash, config=config)
            await s.execute(cfg.on_conflict_do_nothing(index_elements=["config_hash"]))
            row = insert(PolicyDecisionRow).values(**values)
            fields = {k: row.excluded[k] for k in values if k not in ("turn_id", "pass_no")}
            await s.execute(row.on_conflict_do_update(index_elements=["turn_id", "pass_no"], set_=fields))
            await s.commit()

    @store_errors
    async def for_turn(self, turn_id: str) -> list[DecisionRecord]:
        """The passes of a turn by pass number."""
        async with sessionmaker()() as s:
            q = (
                select(PolicyDecisionRow)
                .where(PolicyDecisionRow.turn_id == turn_id)
                .order_by(PolicyDecisionRow.pass_no)
            )
            return [_record(r) for r in (await s.execute(q)).scalars()]

    @store_errors
    async def config(self, config_hash: str) -> JsonObject | None:
        """The config stored under `config_hash`."""
        async with sessionmaker()() as s:
            row = await s.get(PolicyConfigRow, config_hash)
            return dict(row.config) if row is not None else None

    @store_errors
    async def prune(self, before: datetime) -> int:
        """Delete the passes recorded before `before`; returns how many."""
        async with sessionmaker()() as s:
            old = delete(PolicyDecisionRow).where(PolicyDecisionRow.created_at < before)
            deleted = (await s.execute(old.returning(PolicyDecisionRow.turn_id))).all()
            await s.commit()
            return len(deleted)


def _record(r: PolicyDecisionRow) -> DecisionRecord:
    return DecisionRecord(
        chat_id=r.chat_id, turn_id=r.turn_id, pass_no=r.pass_no, case_version=r.case_version, situation=r.situation,
        config_hash=r.config_hash, rules_version=r.rules_version, trail=tuple(TrailStep(**t) for t in r.trail),
        decided_by=r.decided_by, action=r.action, next_node=r.next_node,
    )  # fmt: skip
