"""The registry port's use cases (spec 010 US6-US8): the plan of an area, the sources worth a `site:` query, the
attempts and the truth signals a job reports.

Errors: research works without the registry, so nothing here raises into a job. When a store raises
`RegistryStoreUnavailable` the plan is empty (research keeps its configured order), no source is offered for
`site:` queries, the attempts are not counted, and a signal is not stored (None) — each logged."""

from __future__ import annotations

import logging

from automind.acquisition.domain import thompson
from automind.acquisition.registry.api import Attempt, Outcome, Plan, PlannedSource, TruthSignalIn
from automind.acquisition.registry.application.ports import (
    Capabilities,
    PageMarks,
    RegistryStoreUnavailable,
    Signals,
)
from automind.acquisition.registry.domain import planning
from automind.acquisition.registry.domain.config import RegistryConfig
from automind.acquisition.registry.domain.model import CapabilityStatus
from automind.acquisition.registry.domain.records import CapabilityView

log = logging.getLogger(__name__)


class RegistryService:
    """The registry as research sees it (`registry.api.RegistryPort`)."""

    def __init__(self, capabilities: Capabilities, signals: Signals, pages: PageMarks, cfg: RegistryConfig) -> None:
        self.capabilities = capabilities
        self.signals = signals
        self.pages = pages
        self.cfg = cfg

    @property
    def autonomy(self) -> bool:
        """The registry orders research's sources (`registry.autonomy`)."""
        return self.cfg.autonomy

    async def plan(self, area: str, markets: list[str], make: str | None, seed: int | None = None) -> Plan:
        """Ordered sources for an area. With autonomy off research keeps its configured order (the plan is empty
        apart from the skip list), so storage changes nothing (US8). With autonomy on, active sources are ordered by
        score and the candidates that get an exploration slot are drawn by Thompson sampling (spec 011 R7) while
        today's `explore.eur_per_day` lasts; `seed` (from the job id) makes the draw reproducible."""
        try:
            rows = await self.capabilities.capabilities(area, [*markets, "ANY"])
        except RegistryStoreUnavailable:
            log.exception("registry.plan_failed area=%s", area)
            return Plan(area=area)
        skip = planning.blocked_domains(rows)
        if not self.autonomy:
            return Plan(area=area, autonomy=False, skip=skip)
        active = planning.ordered_active(rows)
        seed = seed if seed is not None else thompson.seed_of(area, *markets)
        explored = await self._explore(rows, {r.domain for r in active}, seed)
        sources = [_planned(r, i, CapabilityStatus.ACTIVE) for i, r in enumerate(active)]
        sources += [_planned(r, len(active) + i, CapabilityStatus.CANDIDATE) for i, r in enumerate(explored)]
        return Plan(area=area, autonomy=True, sources=sources, skip=skip)

    async def sources_for(self, area: str, markets: list[str], limit: int) -> list[PlannedSource]:
        """Active sources first (best score first), then candidates the survey found open (robots and terms);
        never blocked, retired, degraded or merely discovered ones. Allowed with autonomy off: a query is an
        attempt, never a status change (spec 010 US8)."""
        if limit <= 0:
            return []
        try:
            rows = await self.capabilities.queryable(area, markets)
        except RegistryStoreUnavailable:
            log.exception("registry.sources_failed area=%s", area)
            return []
        return [_queryable(r, i) for i, r in enumerate(planning.rank_queryable(rows, markets, limit))]

    async def record(self, attempts: list[Attempt]) -> None:
        """Count a job's attempts, then mark the pages they read (a page with accepted values is kept longer)."""
        if not attempts:
            return
        try:
            await self.capabilities.record(attempts)
        except RegistryStoreUnavailable:
            log.exception("registry.record_failed")
            return
        for a in attempts:
            if a.snapshot_id is not None:
                await self.pages.mark(a.snapshot_id, a.values if a.outcome == Outcome.ACCEPTED else 0, a.variant_id)

    async def signal(self, s: TruthSignalIn) -> str | None:
        """Record a truth signal with its configured weight; returns its id (None when it could not be stored)."""
        try:
            return await self.signals.signal(s, self.cfg.weight_of(s.kind))
        except RegistryStoreUnavailable:
            log.exception("registry.signal_failed")
            return None

    async def _explore(self, rows: list[CapabilityView], taken: set[str], seed: int) -> list[CapabilityView]:
        try:
            spent = await self.capabilities.explore_spent()
        except RegistryStoreUnavailable:
            log.exception("registry.explore_spent_failed")
            return []
        return planning.pick_candidates(rows, taken, self.cfg, planning.exploration(self.cfg, spent, seed))


def _planned(r: CapabilityView, priority: int, status: CapabilityStatus) -> PlannedSource:
    return PlannedSource(domain=r.domain, market=r.market, priority=priority, status=status,
                         unverified=status == CapabilityStatus.CANDIDATE)  # fmt: skip


def _queryable(r: CapabilityView, priority: int) -> PlannedSource:
    active = r.status == CapabilityStatus.ACTIVE  # rank_queryable gives active and candidate ones
    status = CapabilityStatus.ACTIVE if active else CapabilityStatus.CANDIDATE
    path = r.url_patterns[0] if r.url_patterns else ""
    return PlannedSource(domain=r.domain, market=r.market, priority=priority, status=status,
                         unverified=not active, path=path)  # fmt: skip
