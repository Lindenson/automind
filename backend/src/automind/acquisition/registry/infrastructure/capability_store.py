"""The capabilities of the sources and the attempts made on them (`capabilities`, `sources`, `registry_attempts`,
`registry_changes`; spec 010 migration 0016). Every method raises `RegistryStoreUnavailable` when the database
fails; `record` is one transaction."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from automind.acquisition.registry.api import Attempt, Outcome
from automind.acquisition.registry.application.ports import RegistryStoreUnavailable
from automind.acquisition.registry.domain.config import RegistryConfig
from automind.acquisition.registry.domain.model import CapabilityStatus
from automind.acquisition.registry.domain.records import CapabilityView
from automind.acquisition.registry.infrastructure.rows import fade, rescore, view
from automind.shared.infrastructure.db.errors import translate_errors
from automind.shared.infrastructure.db.models import (
    CapabilityRow,
    Claim,
    RegistryAttempt,
    RegistryChange,
    SourceRow,
    now,
)
from automind.shared.infrastructure.db.session import sessionmaker
from automind.shared.infrastructure.metrics import prom

RECENT = 20  # last outcomes kept per capability
QUERYABLE = (CapabilityStatus.ACTIVE, CapabilityStatus.CANDIDATE)


class CapabilityStore:
    """`Capabilities` over the database."""

    def __init__(self, cfg: RegistryConfig) -> None:
        self.cfg = cfg

    @translate_errors(RegistryStoreUnavailable)
    async def capabilities(self, area: str, markets: list[str]) -> list[CapabilityView]:
        """Every capability of the area on these markets, with its source's type and access."""
        async with sessionmaker()() as s:
            q = (
                select(CapabilityRow, SourceRow.source_type, SourceRow.access)
                .outerjoin(SourceRow, SourceRow.domain == CapabilityRow.domain)
                .where(CapabilityRow.area == area, CapabilityRow.market.in_(markets))
            )
            return [view(r, st, acc) for r, st, acc in (await s.execute(q)).all()]

    @translate_errors(RegistryStoreUnavailable)
    async def queryable(self, area: str, markets: list[str]) -> list[CapabilityView]:
        """Active and candidate capabilities with their source's access (for `site:` queries)."""
        async with sessionmaker()() as s:
            q = (
                select(CapabilityRow, SourceRow.access)
                .join(SourceRow, SourceRow.domain == CapabilityRow.domain)
                .where(
                    CapabilityRow.area == area, CapabilityRow.market.in_(markets), CapabilityRow.status.in_(QUERYABLE)
                )  # fmt: skip
            )
            return [view(c, None, access) for c, access in (await s.execute(q)).all()]

    @translate_errors(RegistryStoreUnavailable)
    async def explore_spent(self) -> float:
        """Today's exploration spend over all capabilities (reset by the daily roll-up)."""
        async with sessionmaker()() as s:
            total = select(func.coalesce(func.sum(CapabilityRow.explore_spent_eur), 0.0))
            return float((await s.execute(total)).scalar() or 0.0)

    @translate_errors(RegistryStoreUnavailable)
    async def record(self, attempts: list[Attempt]) -> None:
        """Count each attempt on its capability (faded and rescored) and journal it, in one transaction."""
        types: dict[str, str] = {}
        async with sessionmaker()() as s:
            for a in attempts:
                cap = await _capability(s, a.domain, a.area, a.market)
                _count(cap, a, self.cfg.half_life_days)
                rescore(cap, await _source_type(s, a.domain, types), self.cfg.score)
                version, model = await _producer_of(s, a)
                s.add(RegistryAttempt(
                    capability_id=cap.id, job_id=a.job_id, variant_id=a.variant_id, url=a.url, outcome=a.outcome,
                    reason=a.reason, values=a.values, cost_eur=a.cost_eur, snapshot_id=a.snapshot_id,
                    producer_version=version, model=model, stage_versions=a.stage_versions,
                ))  # fmt: skip
                prom.inc("registry_attempts", area=a.area, outcome=a.outcome)
            await s.commit()


async def source_type(s: AsyncSession, domain: str) -> str:
    """The type of a domain's source ("OTHER" when it has no source row)."""
    src = await s.get(SourceRow, domain)
    return src.source_type if src is not None else "OTHER"


async def _source_type(s: AsyncSession, domain: str, cache: dict[str, str]) -> str:
    if domain not in cache:
        cache[domain] = await source_type(s, domain)
    return cache[domain]


def _count(cap: CapabilityRow, a: Attempt, half_life_days: float) -> None:
    fade(cap, half_life_days, now())
    ok = a.outcome == Outcome.ACCEPTED
    cap.attempts += 1
    cap.accepted += 1 if ok else 0
    if a.outcome == Outcome.ROBOTS:
        cap.robots_refusals += 1
    if a.outcome == Outcome.JUNK:
        cap.junk += 1
    if a.outcome == Outcome.REJECTED and a.reason:
        cap.rejected = {**(cap.rejected or {}), a.reason: float((cap.rejected or {}).get(a.reason, 0)) + 1}
    cap.cost_eur += a.cost_eur
    if cap.status == CapabilityStatus.CANDIDATE:  # spec 011 R7: a candidate's attempt is exploration
        cap.explore_spent_eur = (cap.explore_spent_eur or 0.0) + a.cost_eur
    cap.recent = [*(cap.recent or []), ok][-RECENT:]
    cap.last_used = now()


async def _capability(s: AsyncSession, domain: str, area: str, market: str) -> CapabilityRow:
    q = select(CapabilityRow).where(
        CapabilityRow.domain == domain, CapabilityRow.area == area, CapabilityRow.market == market
    )
    cap = (await s.execute(q)).scalar_one_or_none()
    if cap is not None:
        return cap
    if await s.get(SourceRow, domain) is None:  # met in an open search: discovered (admission comes later)
        s.add(SourceRow(domain=domain, source_type="PUBLICATION", family=domain, markets=[market]))
        await s.flush()
    cap = CapabilityRow(domain=domain, area=area, market=market, status=CapabilityStatus.DISCOVERED)
    s.add(cap)
    await s.flush()
    s.add(RegistryChange(author="system", capability_id=cap.id, domain=domain, change="added",
                         after={"status": CapabilityStatus.DISCOVERED, "area": area, "market": market},
                         reason="met in a research search"))  # fmt: skip
    prom.inc("registry_changes", change="added", author="system")
    return cap


async def _producer_of(s: AsyncSession, a: Attempt) -> tuple[str | None, str | None]:
    """Spec 011 FR-002: an attempt names the producer version and model of the values read from its page."""
    if a.producer_version is not None or a.snapshot_id is None:
        return a.producer_version, a.model
    q = select(Claim.producer_version, Claim.model).where(Claim.snapshot_id == a.snapshot_id)
    if a.variant_id:
        q = q.where(Claim.variant_id == a.variant_id)
    row = (await s.execute(q.order_by(Claim.created_at.desc()).limit(1))).first()
    return (row[0], row[1]) if row else (None, None)
