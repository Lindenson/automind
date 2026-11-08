"""After a job read its pages: every page as an attempt of its source in the registry (spec 010 FR-015), the pages
the extractor read as the shadow gate's feed (spec 011 T102), the area's hits and section minimum, the area's run and
the job's metrics. Every record carries the versions of the stages that produced it (spec 011 FR-002).

Errors: a store failure (`PipelineStoreUnavailable`) and a registry failure propagate (the job fails); the shadow
feed never fails the job (bookkeeping)."""

from __future__ import annotations

import contextlib
from typing import Any

from automind.acquisition.infrastructure import overrides
from automind.acquisition.parsing.extraction import areas
from automind.acquisition.pipeline.application.ports import AreaRun, JobBook, JobMetrics, ValueStore
from automind.acquisition.pipeline.contracts import NO_VALUES, JobSpec, PageOutcome, PageTally
from automind.acquisition.pipeline.domain.hits import hits_of, source_kind
from automind.acquisition.pipeline.domain.variant import VariantFacts
from automind.acquisition.ports import AcqPorts
from automind.acquisition.registry.api import Attempt
from automind.shared import evidence as ev
from automind.shared.contracts.web import Page
from automind.shared.research_order import plan as research_plan
from automind.shared.research_order import search_plan


async def record_attempts(ports: AcqPorts, job: JobSpec, pages: list[Page], outcomes: dict[str, PageOutcome],
                          url_market: dict[str, str], stage_versions: dict[str, str]) -> None:  # fmt: skip
    """Every page a search found (not a denied one) as an attempt of its source for the area; none without the
    registry."""
    if ports.registry is None:
        return
    attempts = []
    for p in pages:
        if p.url not in url_market or ev.is_denied(p.url):
            continue
        o = outcomes.get(p.url, NO_VALUES)
        attempts.append(Attempt(area=job.area, market=url_market[p.url], url=p.url, snapshot_id=p.snapshot_id,
                                outcome=o.outcome, reason=o.reason, values=o.values, job_id=job.job_id,
                                variant_id=job.variant_id, stage_versions=stage_versions))  # fmt: skip
    await ports.registry.record(attempts)


async def feed_shadow(ports: AcqPorts, area: str, pages: list[Page]) -> None:
    """Pages the extractor just read feed the shadow gate of a prompt or model change (queued for the worker; no
    work in the turn); nothing when no such change is in shadow or the engine has no shadow port."""
    if ports.shadow is None or not (overrides.in_shadow("prompt") or overrides.in_shadow("role_model")):
        return
    ids = [p.snapshot_id for p in pages if p.snapshot_id]
    if ids:
        with contextlib.suppress(Exception):  # bookkeeping never fails the job
            await ports.shadow.notify_extracted(areas.PROMPT_FOR_AREA.get(area), ids)


def fold_tally(stats: dict[str, Any], tally: PageTally) -> None:
    """The pages' counts into the search counts: pages rejected by relevance, values rejected, reader values."""
    for k, n in tally.off_topic.items():
        stats["pages_rejected"][k] = stats["pages_rejected"].get(k, 0) + n
    stats["values_rejected"] = dict(tally.values_rejected)
    stats["reader_values"] = tally.reader


async def area_hits(book: JobBook, v: VariantFacts, area: str) -> list[dict[str, Any]]:
    """Accepted evidence per source domain for an area (input to the section minimum); `unverified` marks a
    registry candidate's evidence (counts half, spec 011 FR-022). KeyError: an area with no store of its own."""
    return hits_of(await book.area_sources(v.id, v.make, area, source_kind(area, areas.SPEC_AREAS)))


async def area_met(values: ValueStore, v: VariantFacts, area: str, hits: list[dict[str, Any]]) -> bool:
    """The area's section minimum; the specs area also needs the energy inputs of the powertrain (spec 006 FR-009:
    look deeper before "cannot be computed")."""
    met = research_plan.minimum_met(area, [research_plan.SourceHit(**h) for h in hits])
    if met and area == "specs" and research_plan.energy_inputs_missing(v.powertrain, await values.available(v.id)):
        return False
    return met


async def mark_run(book: JobBook, variant_id: str, job: JobSpec, counts: tuple[int, int, int], met: bool,
                   stage_versions: dict[str, str], *, registry: bool = False) -> None:  # fmt: skip
    """The area's run: `counts` = (pages read, accepted, rejected); `registry`: the job tried the registry's sources
    with the escalation to the other markets (kept otherwise)."""
    docs, acc, rej = counts
    run = AreaRun(variant_id=variant_id, area=job.area, docs=docs, accepted=acc, rejected=rej, rounds=job.round,
                  minimum_met=met, registry=registry, stage_versions=stage_versions)  # fmt: skip
    await book.mark_run(run, brand_positioning=job.area == "manufacturer")


async def record_metrics(book: JobBook, job_id: str, planned: list[search_plan.PlannedQuery],
                         stats: dict[str, Any]) -> None:  # fmt: skip
    """The job's queries (each marked empty when it found nothing) and its page and value counts."""
    empty = {(q.text, q.market) for q in stats.get("empty_queries", [])}
    queries = [{"text": q.text, "kind": q.kind, "market": q.market, "empty": (q.text, q.market) in empty}
               for q in planned]  # fmt: skip
    await book.record_metrics(job_id, JobMetrics(queries=queries, pages_found=stats["pages_found"],
                                                 pages_cached=stats["pages_cached"],
                                                 pages_rejected=stats["pages_rejected"],
                                                 values_rejected=stats.get("values_rejected") or None,
                                                 reader_values=int(stats.get("reader_values") or 0)))  # fmt: skip
