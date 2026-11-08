"""The review's unit of work (`capabilities`, `sources`, `registry_changes`, `registry_runs`; spec 010 US7): one
transaction loads every capability faded and rescored to now, then writes the moves, the journal and the run.
Raises `RegistryStoreUnavailable` when the database fails; nothing of a failed run is written."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from automind.acquisition.registry.application.ports import RegistryStoreUnavailable
from automind.acquisition.registry.domain.config import RegistryConfig
from automind.acquisition.registry.domain.records import ReviewedCapability, SourceState
from automind.acquisition.registry.domain.review import ReviewFacts, ReviewPlan
from automind.acquisition.registry.infrastructure.rows import fade, rescore, reviewed
from automind.shared.infrastructure.db.models import CapabilityRow, RegistryChange, RegistryRun, SourceRow, now
from automind.shared.infrastructure.db.session import sessionmaker
from automind.shared.infrastructure.metrics import prom


class ReviewStore:
    """`ReviewBook` over the database."""

    def __init__(self, cfg: RegistryConfig) -> None:
        self.cfg = cfg

    @asynccontextmanager
    async def session(self, kind: str) -> AsyncIterator[ReviewRun]:
        """A review run in one transaction, committed when the block ends without an error."""
        try:
            async with sessionmaker()() as s:
                run = ReviewRun(s, RegistryRun(kind=kind), self.cfg)
                s.add(run.row)
                yield run
                run.row.finished_at = now()
                await s.commit()
        except (SQLAlchemyError, OSError) as e:
            raise RegistryStoreUnavailable(f"ReviewStore.session: {type(e).__name__}") from e


class ReviewRun:
    """One open review run (`ReviewSession`)."""

    def __init__(self, s: AsyncSession, row: RegistryRun, cfg: RegistryConfig) -> None:
        self.s = s
        self.row = row
        self.cfg = cfg
        self.caps: dict[str, CapabilityRow] = {}

    async def load(self) -> tuple[list[ReviewedCapability], ReviewFacts]:
        """Every capability faded and rescored to now, with the sources' state and the owner's reverts."""
        caps = list((await self.s.execute(select(CapabilityRow))).scalars())
        sources = {r.domain: r for r in (await self.s.execute(select(SourceRow))).scalars()}
        out = []
        for c in caps:
            score_before = float(c.score)
            src = sources.get(c.domain)
            fade(c, self.cfg.half_life_days, now())
            rescore(c, src.source_type if src else "OTHER", self.cfg.score)
            out.append(reviewed(c, score_before))
        self.caps = {c.id: c for c in caps}
        states = {d: SourceState(r.access, bool(r.frozen)) for d, r in sources.items()}
        return out, ReviewFacts(states, await self._reverts())

    def apply(self, plan: ReviewPlan) -> None:
        """Stage the moves (status since now), the journal and the run's count of changes."""
        t = now()
        for m in plan.moves:
            self.caps[m.capability_id].status, self.caps[m.capability_id].status_since = m.to, t
        for e in plan.journal:
            self.s.add(RegistryChange(author="system", capability_id=e.capability_id, domain=e.domain,
                                      change=e.change, before=e.before, after=e.after, reason=e.reason,
                                      evidence=e.evidence, held=e.held))  # fmt: skip
            if not e.held:
                prom.inc("registry_changes", change=e.change, author="system")
        self.row.changes = plan.stats["changes"] + plan.stats["reordered"]

    async def _reverts(self) -> dict[str, datetime]:
        out: dict[str, datetime] = {}
        q = select(RegistryChange).where(RegistryChange.change == "reverted")
        for ch in (await self.s.execute(q)).scalars():
            if ch.capability_id and (ch.capability_id not in out or ch.created_at > out[ch.capability_id]):
                out[ch.capability_id] = ch.created_at
        return out
