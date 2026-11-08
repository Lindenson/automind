"""S7 job (spec 011, research R5; spec 002 R8, R14, FR-013..FR-023): one research job = one car × one area.

`ResearchJob.run` opens the job's scope (overrides, the registry's plan), then for a car area: search (plan → locate
→ fetch) → read the pages (relevance → table reader or extraction → validate → persist) → the registry attempts and
the shadow feed → select the values (merge) → the area's hits, minimum and run → the job's metrics. A market area
(incentives) has no relevance gate and stores facts per market. The stages are `stages/`; every record carries
`STAGE_VERSIONS`.

Errors: BudgetExceeded propagates (counted "budget"; the turn stops researching). Any other failure — an unknown
variant, a store down (`PipelineStoreUnavailable`), a search or registry error — fails this job only: a failed
`JobResult` and a "failed" progress line, never an exception (one failing job never fails the turn, FR-023). What a
job stored before it failed stays (each page is its own transaction). One failing source never fails the job.

Constitution I (evidence first), III (code normalizes numbers), VIII (untrusted content), XI (gates), XIII.
"""

from __future__ import annotations

from automind.acquisition.parsing.extraction import areas
from automind.acquisition.pipeline import fetch, locate, market, parse, persist, plan, relevance, validate
from automind.acquisition.pipeline.application import selection
from automind.acquisition.pipeline.application.selection import ValueSelection
from automind.acquisition.pipeline.contracts import Emit, Found, JobResult, JobSpec
from automind.acquisition.pipeline.domain.critical import missing_critical
from automind.acquisition.pipeline.domain.target import target_of
from automind.acquisition.pipeline.domain.variant import VariantFacts
from automind.acquisition.pipeline.home_market import home_market, home_target
from automind.acquisition.pipeline.plan import variant
from automind.acquisition.pipeline.searches import pages_for
from automind.acquisition.pipeline.stages import book
from automind.acquisition.pipeline.stages.car_pages import read_car_pages
from automind.acquisition.pipeline.stages.market_pages import read_market_pages
from automind.acquisition.pipeline.stages.opening import active_sources, opened
from automind.acquisition.ports import AcqPorts
from automind.shared.metering.usage import BudgetExceeded
from automind.shared.research_order import plan as research_plan

VERSION = "job@1"
# spec 011 FR-002: the versions of the stages a job ran, on every attempt and on the area's research run
_STAGES = (plan, locate, fetch, relevance, parse, validate, persist, selection, market)
STAGE_VERSIONS = {**{m.VERSION.split("@")[0]: m.VERSION for m in _STAGES}, "job": VERSION}


class ResearchJob:
    """One research job over the engine's ports (search, pages, readers, roles, registry, stores, metrics)."""

    def __init__(self, ports: AcqPorts) -> None:
        self.ports = ports

    async def run(self, job: JobSpec, emit: Emit) -> JobResult:
        """Research one area of one car (see the module docstring for the stages and the errors)."""
        async with opened(self.ports, job) as the_plan:
            try:
                research = self._market if job.area in research_plan.MARKET_AREAS else self._car
                result = await research(job, emit)
                result.planned = active_sources(the_plan)
                self._count(job, "ok" if result.ok else "failed")
                return result
            except BudgetExceeded:
                self._count(job, "budget")
                raise
            except Exception as e:  # one failing job never fails the turn (FR-023)
                self._count(job, "error")
                await emit("researching", f"{job.area}: failed ({type(e).__name__})")
                return JobResult(job.job_id, job.variant_id, job.area, job.round, ok=False,
                                 error=f"{type(e).__name__}: {e}")  # fmt: skip

    async def _car(self, job: JobSpec, emit: Emit) -> JobResult:
        """A car area: search, read the pages, record them, select the values, close the area."""
        ports = self.ports
        v = await variant(ports, job.variant_id)
        found = await self._search(v, job, emit, await self._missing(v, job))
        target = target_of(v, job.car_year, home_target(ports, v, home_market(v, job)))
        await emit("reading", f"{job.area}: reading {len(found.pages)} sources "
                              f"({found.stats['pages_cached']} from cache)")  # fmt: skip
        tally = await read_car_pages(ports, v, job, found.pages, target)
        await book.feed_shadow(ports, job.area, tally.shadow_pages(found.pages))
        await book.record_attempts(ports, job, found.pages, tally.outcomes, found.stats.get("url_market", {}),
                                   STAGE_VERSIONS)  # fmt: skip
        book.fold_tally(found.stats, tally)
        if tally.off_topic:
            await emit("relevance", f"{job.area}: {sum(tally.off_topic.values())} of {len(found.pages)} pages "
                                    "rejected (other variant)")  # fmt: skip
        if job.area in areas.SPEC_AREAS or job.area == "maintenance":
            await ValueSelection(ports.stores.values).reselect(v.id)
        hits = await book.area_hits(ports.stores.book, v, job.area)
        met = await book.area_met(ports.stores.values, v, job.area, hits)
        counts = (tally.docs, tally.accepted, tally.rejected)
        await book.mark_run(ports.stores.book, v.id, job, counts, met, STAGE_VERSIONS, registry=job.escalated)
        await book.record_metrics(ports.stores.book, job.job_id, found.planned, found.stats)
        await emit("validating", f"{job.area}: {tally.accepted} accepted, {tally.rejected} rejected by validation")
        return JobResult(job.job_id, v.id, job.area, job.round, docs=tally.docs, accepted=tally.accepted,
                         rejected=tally.rejected, minimum_met=met, hits=hits)  # fmt: skip

    async def _market(self, job: JobSpec, emit: Emit) -> JobResult:
        """A market-level area (spec 006 US5): search, read the pages as market facts, close the area."""
        ports = self.ports
        v = await variant(ports, job.variant_id)
        found = await self._search(v, job, emit, [])
        await emit("reading", f"{job.area}: reading {len(found.pages)} sources")
        tally = await read_market_pages(ports, v, job.area, found.pages)
        hits = tally.hits()
        met = research_plan.minimum_met(job.area, [research_plan.SourceHit(**h) for h in hits])
        counts = (tally.docs, tally.accepted, tally.rejected)
        await book.mark_run(ports.stores.book, v.id, job, counts, met, STAGE_VERSIONS)
        await book.record_metrics(ports.stores.book, job.job_id, found.planned, found.stats)
        await emit("validating", f"{job.area}: {tally.accepted} accepted, {tally.rejected} rejected")
        return JobResult(job.job_id, v.id, job.area, job.round, docs=tally.docs, accepted=tally.accepted,
                         rejected=tally.rejected, minimum_met=met, hits=hits)  # fmt: skip

    async def _missing(self, v: VariantFacts, job: JobSpec) -> list[str]:
        """The critical values the specs area still lacks (they shape the follow-up queries); none for other areas."""
        if job.area != "specs":
            return []
        return missing_critical(await self.ports.stores.values.available(v.id), v.powertrain)

    async def _search(self, v: VariantFacts, job: JobSpec, emit: Emit, missing: list[str]) -> Found:
        """The job's whole search past the pages the variant already used (`searches.pages_for`)."""
        seen = await self.ports.stores.book.used_urls(v.id)
        return Found(*await pages_for(self.ports, v, job, missing, seen, emit))

    def _count(self, job: JobSpec, status: str) -> None:
        """The research_jobs counter (spec 010: Prometheus through the port; nothing without it)."""
        if self.ports.metrics is not None:
            self.ports.metrics("research_jobs", area=job.area, status=status)
