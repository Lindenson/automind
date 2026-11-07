"""The gates' experiments (`acq_experiments`, spec 011 US5 T101-T103): the corpus a gate measures on, pinned so
retention never removes it while the gates run, unpinned back to the class the page earned once decided (unless
another open experiment holds it); the shadow's pages and metrics, the watch's days. Implements `ports.Experiments`;
a database failure becomes `GateStoreUnavailable`."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select, text, update

from automind.acquisition.domain import gates
from automind.acquisition.gates.application.ports import GateStoreUnavailable
from automind.acquisition.infrastructure import config as acq_config
from automind.acquisition.snapshots import codec
from automind.shared.contracts.json import JsonObject
from automind.shared.infrastructure.db.errors import translate_errors
from automind.shared.infrastructure.db.models import AcqExperiment, PageSnapshot
from automind.shared.infrastructure.db.session import sessionmaker

_store_errors = translate_errors(GateStoreUnavailable)
_HELD = text("SELECT DISTINCT unnest(corpus) FROM acq_experiments WHERE decided_at IS NULL AND corpus && :ids")
_APPEND = text(
    "UPDATE acq_experiments SET corpus = array_append(corpus, CAST(:sid AS varchar(36))) "
    "WHERE change_id = :c AND NOT (CAST(:sid AS varchar(36)) = ANY(corpus))"
)


class ExperimentRepo:
    """The experiments and their pinned pages."""

    @_store_errors
    async def pin(self, change_id: str, phase: str, ids: list[str], now: datetime) -> None:
        """The corpus set to `ids` and pinned; pages dropped from it unpinned."""
        async with sessionmaker()() as s:
            exp = await s.get(AcqExperiment, change_id)
            old = list(exp.corpus or []) if exp is not None else []
            if exp is None:
                s.add(AcqExperiment(change_id=change_id, phase=phase, started_at=now, corpus=ids, daily={}))
            else:
                exp.phase, exp.corpus = phase, ids
            if ids:
                await s.execute(update(PageSnapshot).where(PageSnapshot.id.in_(ids))
                                .values(retention_class=codec.PINNED, keep_until=None))  # fmt: skip
            await s.commit()
        if dropped := sorted(set(old) - set(ids)):
            await self._unpin(dropped)

    @_store_errors
    async def decide(self, change_id: str, decision: str, now: datetime) -> None:
        """The experiment decided; its pages unpinned unless another open experiment holds them."""
        async with sessionmaker()() as s:
            exp = await s.get(AcqExperiment, change_id)
            if exp is None:
                return
            exp.decided_at, exp.decision = now, decision
            ids = list(exp.corpus or [])
            await s.commit()
        await self._unpin(ids)

    @_store_errors
    async def start_shadow(self, change_id: str, now: datetime, ends: datetime) -> None:
        """The shadow phase started: no pages, no metrics yet."""
        async with sessionmaker()() as s:
            exp = await s.get(AcqExperiment, change_id)
            if exp is not None:
                exp.started_at, exp.ends_at = now, ends
                exp.pages_old = exp.pages_new = 0
                exp.metrics_old, exp.metrics_new = None, None
                await s.commit()

    @_store_errors
    async def add_page(self, change_id: str, snapshot_id: str) -> None:
        """A live page added to the shadow corpus atomically (shadow tasks run concurrently) and pinned."""
        async with sessionmaker()() as s:
            await s.execute(_APPEND, {"c": change_id, "sid": snapshot_id})
            await s.execute(update(PageSnapshot).where(PageSnapshot.id == snapshot_id)
                            .values(retention_class=codec.PINNED, keep_until=None))  # fmt: skip
            await s.commit()

    @_store_errors
    async def corpus(self, change_id: str) -> tuple[list[str], datetime | None]:
        """The experiment's pages and when its phase started."""
        async with sessionmaker()() as s:
            exp = await s.get(AcqExperiment, change_id)
        if exp is None:
            return [], None
        return list(exp.corpus or []), exp.started_at

    @_store_errors
    async def record(self, change_id: str, old: gates.Metrics, new: gates.Metrics) -> None:
        """The latest metrics of both versions."""
        async with sessionmaker()() as s:
            e = await s.get(AcqExperiment, change_id)
            if e is not None:
                e.pages_old, e.pages_new = old.pages, new.pages
                e.metrics_old, e.metrics_new = old.as_dict(), new.as_dict()
                await s.commit()

    @_store_errors
    async def record_day(self, change_id: str, day: str, values: JsonObject) -> None:
        """One day of the watch."""
        async with sessionmaker()() as s:
            exp = await s.get(AcqExperiment, change_id)
            if exp is not None:
                exp.daily = {**(exp.daily or {}), day: values}
                await s.commit()

    async def _unpin(self, ids: list[str]) -> None:
        """Back to the class the page earned (plain or accepted), unless an open experiment still holds it."""
        if not ids:
            return
        rc = acq_config.snapshot_retention()
        async with sessionmaker()() as s:
            held = {str(x) for (x,) in (await s.execute(_HELD, {"ids": ids})).all()}
            q = select(PageSnapshot).where(PageSnapshot.id.in_([i for i in ids if i not in held]),
                                           PageSnapshot.retention_class == codec.PINNED)  # fmt: skip
            for r in (await s.execute(q)).scalars():
                cls = codec.retention_class(r.accepted_values, pinned=False)
                r.retention_class, r.keep_until = cls, codec.keep_until(r.fetched_at, cls, rc)
            await s.commit()
