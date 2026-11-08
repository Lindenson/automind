"""A research job's book: the pages a variant already used, the job's metrics (`research_jobs`), the area's run
(`research_runs`, with the make's positioning for the manufacturer area) and the sources of the area's accepted
values. Implements `ports.JobBook`; a database failure becomes `PipelineStoreUnavailable`."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from automind.acquisition.pipeline.application.ports import AreaRun, JobMetrics, PipelineStoreUnavailable
from automind.acquisition.pipeline.domain.hits import SourceKind, SourceRef
from automind.acquisition.pipeline.domain.selection import positioning_vote
from automind.acquisition.pipeline.infrastructure import area_sources
from automind.shared.infrastructure.db import models as m
from automind.shared.infrastructure.db.errors import translate_errors
from automind.shared.infrastructure.db.session import sessionmaker

_store_errors = translate_errors(PipelineStoreUnavailable)


class JobBookRepo:
    """Used pages, job metrics, area runs and sources."""

    @_store_errors
    async def used_urls(self, variant_id: str) -> set[str]:
        """URLs already stored as the variant's evidence."""
        async with sessionmaker()() as s:
            rows = await s.execute(select(m.Evidence.url).where(m.Evidence.variant_id == variant_id))
            return {str(u) for u in rows.scalars()}

    @_store_errors
    async def record_metrics(self, job_id: str, metrics: JobMetrics) -> None:
        """The job row's metrics and its search cost so far; nothing when the job row is gone."""
        async with sessionmaker()() as s:
            cost = (await s.execute(select(func.coalesce(func.sum(m.SearchCall.cost_eur), 0))
                                    .where(m.SearchCall.job_id == job_id))).scalar_one()  # fmt: skip
            job = await s.get(m.ResearchJob, job_id)
            if job is None:
                return
            job.queries = metrics.queries
            job.pages_found = metrics.pages_found
            job.pages_cached = metrics.pages_cached
            job.pages_rejected = {**(job.pages_rejected or {}), **metrics.pages_rejected}
            job.search_cost_eur = float(cost or 0)  # coalesce: never None
            job.values_rejected = metrics.values_rejected
            job.reader_values = metrics.reader_values
            await s.commit()

    @_store_errors
    async def area_sources(self, variant_id: str, make: str, area: str, kind: SourceKind) -> list[SourceRef]:
        """The sources of the area's accepted values. Raises KeyError for an area with no store of its own."""
        async with sessionmaker()() as s:
            return await area_sources.of(s, variant_id, make, area, kind)

    @_store_errors
    async def mark_run(self, run: AreaRun, *, brand_positioning: bool = False) -> None:
        """Replace the area's run row (keeping the registry time unless this run tried the registry)."""
        async with sessionmaker()() as s:
            where = (m.ResearchRun.variant_id == run.variant_id, m.ResearchRun.area == run.area)
            old = (await s.execute(select(m.ResearchRun.registry_at).where(*where))).scalars().first()
            await s.execute(delete(m.ResearchRun).where(*where))
            s.add(m.ResearchRun(variant_id=run.variant_id, area=run.area, docs_used=run.docs,
                                claims_accepted=run.accepted, claims_rejected=run.rejected, rounds_used=run.rounds,
                                minimum_met=run.minimum_met, registry_at=datetime.now(UTC) if run.registry else old,
                                stage_versions=run.stage_versions))  # fmt: skip
            if brand_positioning:
                await _brand_positioning(s, run.variant_id)
            await s.commit()


async def _brand_positioning(s: AsyncSession, variant_id: str) -> None:
    """Status indicator (FR-028): the make's positioning only from its sourced MARKET_POSITION facts."""
    v = await s.get(m.Variant, variant_id)
    if v is None:
        return
    stated = (await s.execute(select(m.ManufacturerFact.positioning).where(
        m.ManufacturerFact.make == v.make, m.ManufacturerFact.positioning.is_not(None)))).scalars()  # fmt: skip
    best = positioning_vote([str(p) for p in stated])
    if best is not None:
        for other in (await s.execute(select(m.Variant).where(m.Variant.make == v.make))).scalars():
            other.brand_positioning = best
