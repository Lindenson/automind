"""The change journal's store (`acq_changes`, spec 011 US5 T100): rows read as `Change`, a proposal written with its
candidate object in one transaction, transitions claimed atomically, the restore of a rollback journalled, and the
wrong signals blamed to a new version. Implements `ports.ChangeStore`; a database failure becomes
`GateStoreUnavailable`."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Unpack

from pydantic import BaseModel
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError

from automind.acquisition.agents import levers
from automind.acquisition.domain.gates import ChangeStatus
from automind.acquisition.gates.application.ports import ChangeFields, GateStoreUnavailable
from automind.acquisition.gates.domain.change import AGENT, Change, sentence
from automind.acquisition.gates.infrastructure.candidates import candidate
from automind.shared.contracts.json import JsonObject
from automind.shared.infrastructure.db.errors import translate_errors
from automind.shared.infrastructure.db.models import AcqChange, uid
from automind.shared.infrastructure.db.session import sessionmaker

_store_errors = translate_errors(GateStoreUnavailable)
_WRONG = text("SELECT count(*) FROM truth_signals WHERE verdict = 'wrong' AND created_at >= :t AND component LIKE :c")


class ChangeRepo:
    """The journal's rows."""

    @_store_errors
    async def load(self, change_id: str) -> Change | None:
        """The change, None when there is none."""
        async with sessionmaker()() as s:
            row = await s.get(AcqChange, change_id)
            return change_of(row) if row is not None else None

    @_store_errors
    async def propose(self, change_id: str, agent: str, proposal: BaseModel, reason: str, evidence: JsonObject,
                      cost_eur: float, now: datetime) -> Change | None:  # fmt: skip
        """The candidate object and the `proposed` row in one transaction; None when the object has an open change."""
        kind, key = levers.object_of(proposal)
        try:
            async with sessionmaker()() as s:
                cand = await candidate(s, change_id, agent, proposal)
                c = Change(id=change_id, author=AGENT + agent, object_kind=kind, object_key=key,
                           from_version=cand.from_version, to_version=cand.to_version, status="proposed",
                           diff=cand.diff, diff_hash=levers.diff_hash(proposal), reason=reason, evidence=evidence,
                           created_at=now)  # fmt: skip
                c = replace(c, explanation=sentence(c))
                s.add(AcqChange(id=c.id, created_at=now, author=c.author, object_kind=kind, object_key=key,
                                from_version=c.from_version, to_version=c.to_version, diff=c.diff,
                                diff_hash=c.diff_hash, reason=reason, evidence=evidence, gates={}, status="proposed",
                                explanation=c.explanation, cost_eur=cost_eur))  # fmt: skip
                await s.commit()
        except IntegrityError:  # the partial unique index: one open change per object
            return None
        return c

    @_store_errors
    async def claim(self, change_id: str, expected: tuple[str, ...], status: str) -> Change | None:
        """Move an open change from one of `expected` to `status` atomically; None when another task moved it."""
        async with sessionmaker()() as s:
            q = (update(AcqChange).where(AcqChange.id == change_id, AcqChange.status.in_(expected),
                                         AcqChange.closed_at.is_(None))
                 .values(status=status).returning(AcqChange.id))  # fmt: skip
            got = (await s.execute(q)).scalar_one_or_none()
            await s.commit()
        return await self.load(change_id) if got else None

    @_store_errors
    async def update(self, change_id: str, **fields: Unpack[ChangeFields]) -> Change:
        """Set the fields; returns the change as stored. Raises KeyError for an unknown change."""
        async with sessionmaker()() as s:
            row = await s.get(AcqChange, change_id)
            if row is None:
                raise KeyError(change_id)
            for k, v in fields.items():
                setattr(row, k, v)
            await s.commit()
            await s.refresh(row)
            return change_of(row)

    @_store_errors
    async def journal_restore(self, of: Change, by: str, explanation: str, evidence: JsonObject,
                              now: datetime) -> str:  # fmt: skip
        """A closed row journalling the restore of `of`'s previous version; returns its id."""
        row_id = uid()
        async with sessionmaker()() as s:
            s.add(AcqChange(id=row_id, created_at=now, author=by, object_kind=of.object_kind, object_key=of.object_key,
                            from_version=of.to_version, to_version=of.from_version, diff={"rollback_of": of.id},
                            diff_hash=of.diff_hash, reason="rollback", evidence=evidence, gates={}, status="accepted",
                            explanation=explanation, cost_eur=0, closed_at=now))  # fmt: skip
            await s.commit()
        return row_id

    @_store_errors
    async def ids_in(self, status: str) -> list[str]:
        """The open changes in `status`."""
        async with sessionmaker()() as s:
            q = select(AcqChange.id).where(AcqChange.status == status, AcqChange.closed_at.is_(None))
            return [str(i) for (i,) in (await s.execute(q)).all()]

    @_store_errors
    async def in_shadow(self, kinds: tuple[str, ...]) -> list[Change]:
        """The open changes of these kinds in shadow."""
        async with sessionmaker()() as s:
            q = select(AcqChange).where(AcqChange.status == ChangeStatus.SHADOW, AcqChange.closed_at.is_(None),
                                        AcqChange.object_kind.in_(list(kinds)))  # fmt: skip
            return [change_of(r) for r in (await s.execute(q)).scalars()]

    @_store_errors
    async def wrong_signals(self, component_like: str, since: datetime) -> int:
        """Wrong truth signals blamed to components matching the pattern since `since`."""
        async with sessionmaker()() as s:
            return int((await s.execute(_WRONG, {"t": since, "c": component_like})).scalar() or 0)


def change_of(row: AcqChange) -> Change:
    """A row as a `Change`."""
    return Change(
        id=row.id, author=row.author, object_kind=row.object_kind, object_key=row.object_key,
        from_version=row.from_version, to_version=row.to_version, status=row.status, diff=dict(row.diff or {}),
        diff_hash=row.diff_hash, reason=row.reason, evidence=dict(row.evidence or {}), gates=dict(row.gates or {}),
        explanation=row.explanation, created_at=row.created_at, closed_at=row.closed_at,
        metrics_before=row.metrics_before,
    )  # fmt: skip
