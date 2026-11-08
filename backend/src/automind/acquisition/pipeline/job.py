"""S7 job (spec 011 strangler, research R5; spec 002 R8, R14, FR-013..FR-023): one research job = one car × one area.

run_job: plan the queries → locate (search with the cache, rank) → fetch pages → relevance → parse (site readers) or
extract (web reader, no tools) → validate (verbatim excerpts, units, ranges, sense, the validator role) → persist
evidence and items → merge the selected values → area freshness and section minimum. Every page read from a search is
an attempt of its source in the registry, journalled with the versions of the stages that produced it. One failing
source never fails the job; one failing job never fails the turn.

Constitution I (evidence first), III (code normalizes numbers), VIII (untrusted content), XI (gates), XIII.
Moved from `application/research.py` with the bodies unchanged (plus `stage_versions`).
"""

from __future__ import annotations

import asyncio
import contextlib
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from automind.acquisition.domain import relevance as rel
from automind.acquisition.infrastructure import overrides
from automind.acquisition.pipeline import extract as ex
from automind.acquisition.pipeline import fetch, locate, market, parse, persist, plan, relevance, validate
from automind.acquisition.pipeline.application import selection
from automind.acquisition.pipeline.application.ports import AreaRun, JobBook, JobMetrics
from automind.acquisition.pipeline.application.selection import ValueSelection
from automind.acquisition.pipeline.domain.hits import hits_of, source_kind
from automind.acquisition.pipeline.domain.variant import VariantFacts
from automind.acquisition.pipeline.parse import _read_tables
from automind.acquisition.pipeline.persist import evidence_in, persist_extraction, persist_reading
from automind.acquisition.pipeline.plan import _plan, current_candidates, current_plan, known_makes, variant
from automind.acquisition.pipeline.relevance import _llm_per_job, _PageJudge, _relevance_target
from automind.acquisition.pipeline.searches import pages_for
from automind.acquisition.ports import AcqPorts
from automind.acquisition.read import _have, missing_critical
from automind.acquisition.registry.api import Attempt
from automind.shared import evidence as ev
from automind.shared.contracts.web import Page
from automind.shared.metering.usage import BudgetExceeded, current_job
from automind.shared.research_order import plan as research_plan
from automind.shared.research_order import search_plan

VERSION = "job@1"
# spec 011 FR-002: the versions of the stages a job ran, on every attempt and on the area's research run
_STAGES = (plan, locate, fetch, relevance, parse, validate, persist, selection, market)
STAGE_VERSIONS = {**{m.VERSION.split("@")[0]: m.VERSION for m in _STAGES}, "job": VERSION}


Emit = Callable[[str, str], Awaitable[None]]


@dataclass
class JobSpec:
    job_id: str
    variant_id: str
    area: str
    round: int = 0
    car_year: int | None = None  # the user's car year (validator compares claims with the case, FR-016)
    fresh: bool = False  # the user asked to search again: bypass the search cache and widen the queries
    escalate: bool = False  # an area left short: round 0 also queries the registry's other markets (010 FR-022)
    market: str | None = None  # where the car is sold when not in Spain (CaseCar.market; chat 2026-11-06)

    @property
    def escalated(self) -> bool:
        """The job queries the registry's sources of the other markets (a follow-up round, "find it", a retry)."""
        return self.round > 0 or self.fresh or self.escalate


@dataclass
class JobResult:
    job_id: str
    variant_id: str
    area: str
    round: int
    ok: bool = True
    docs: int = 0
    accepted: int = 0
    rejected: int = 0
    minimum_met: bool = False
    error: str | None = None
    hits: list[dict[str, Any]] = field(default_factory=list)
    planned: list[str] = field(default_factory=list)  # the active sources of the registry's plan (not_reached input)


def target_of(v: VariantFacts, car_year: int | None = None, home: str | None = None) -> str:
    """The car for the extractor, the relevance role and the validator. `home`: what `plan.home_target` says about
    a car sold only outside Europe (its market, its local name, how its pages label the figures)."""
    years = f" ({v.generation_years_from}–{v.generation_years_to or 'now'})" if v.generation_years_from else ""
    body = f", body {v.body_class.lower()}" if v.body_class else ""
    year = f", the user's car is from ~{car_year}" if car_year else ""
    return f"{v.label}{years}, powertrain {v.powertrain}{body}, {home or 'market ES'}{year}"


PageOutcome = tuple[str, str | None, int]  # (attempt outcome, reason, accepted values)


async def _record_registry(ports: AcqPorts, job: JobSpec, pages: list[Page], outcome_by_url: dict[str, PageOutcome],
                           url_market: dict[str, str]) -> None:  # fmt: skip
    """Every page read from a search is an attempt of its source for this kind of data (spec 010 FR-015)."""
    if ports.registry is None:
        return
    attempts = []
    for p in pages:
        if p.url not in url_market or ev.is_denied(p.url):
            continue
        outcome, reason, n = outcome_by_url.get(p.url, ("empty", None, 0))
        attempts.append(Attempt(area=job.area, market=url_market[p.url], url=p.url, snapshot_id=p.snapshot_id,
                                outcome=outcome, reason=reason, values=n, job_id=job.job_id,  # type: ignore[arg-type]
                                variant_id=job.variant_id,
                                stage_versions=STAGE_VERSIONS))  # fmt: skip
    await ports.registry.record(attempts)


async def _shadow_extracted(area: str, pages: list[Page]) -> None:
    """Spec 011 T102: pages the extractor just read feed the shadow gate of a prompt or model change (queued for the
    worker; no work in the turn)."""
    if not (overrides.in_shadow("prompt") or overrides.in_shadow("role_model")):
        return
    from automind.acquisition.gates.infrastructure.wiring import shadow_gate  # noqa: PLC0415

    ids = [p.snapshot_id for p in pages if p.snapshot_id]
    if ids:
        with contextlib.suppress(Exception):  # bookkeeping never fails the job
            await shadow_gate().notify_extracted(ex.PROMPT_FOR_AREA.get(area), ids)


async def run_job(ports: AcqPorts, job: JobSpec, emit: Emit) -> JobResult:
    await overrides.refresh()  # spec 011 T104: gated rule, prompt and model overrides (cached 60 s)
    token = current_job.set((job.job_id, job.area))
    the_plan = await _plan(ports, job)
    plan_token = current_plan.set(the_plan)
    cand_token = current_candidates.set(set())
    count = ports.metrics or (lambda *a, **k: None)  # spec 010: Prometheus counters through the port
    try:
        result = await (_run_market if job.area in research_plan.MARKET_AREAS else _run)(ports, job, emit)
        if the_plan is not None:
            result.planned = list(dict.fromkeys(x.domain for x in the_plan.sources if x.status == "active"))
        count("research_jobs", area=job.area, status="ok" if result.ok else "failed")
        return result
    except BudgetExceeded:
        count("research_jobs", area=job.area, status="budget")
        raise
    except Exception as e:  # one failing job never fails the turn (FR-023)
        count("research_jobs", area=job.area, status="error")
        await emit("researching", f"{job.area}: failed ({type(e).__name__})")
        return JobResult(job.job_id, job.variant_id, job.area, job.round, ok=False, error=f"{type(e).__name__}: {e}")
    finally:
        current_candidates.reset(cand_token)
        current_plan.reset(plan_token)
        current_job.reset(token)


async def _run(ports: AcqPorts, job: JobSpec, emit: Emit) -> JobResult:
    v = await variant(ports, job.variant_id)
    missing = await missing_critical(v.id, v.powertrain) if job.area == "specs" else []
    seen = await ports.stores.book.used_urls(v.id)
    planned, pages, stats = await pages_for(ports, v, job, missing, seen, emit)
    target = target_of(v, job.car_year, plan.home_target(ports, v, plan.home_market(v, job)))
    # One pipeline per page (spec 004 FR-032): relevance → table reader or extraction → validation → storage.
    # Pages run concurrently; the model calls are bounded per job here and in total by the gateway.
    await emit("reading", f"{job.area}: reading {len(pages)} sources ({stats['pages_cached']} from cache)")
    tgt, gens = _relevance_target(v, ports)
    judge = _PageJudge(ports, v, tgt, gens, target, job.area)
    makes = known_makes(ports)
    sem = asyncio.Semaphore(_llm_per_job(ports))
    known = await ports.stores.values.known_values(v.id)
    readings = await _read_tables(ports, v, pages) if job.area in ex.SPEC_AREAS else {}
    gate: dict[str, int] = defaultdict(int)
    values_rejected: dict[str, int] = defaultdict(int)
    totals = {"accepted": 0, "rejected": 0, "reader": 0, "docs": 0}
    outcome_by_url: dict[str, PageOutcome] = {}  # spec 010: attempt outcome per page

    brand = job.area in research_plan.BRAND_AREAS

    async def one(p: Page) -> None:
        r = rel.judge_brand(rel.PageFacts(p.url, p.title, p.text), v.make, makes) if brand else await judge(p)
        if r.verdict in ("OTHER_VARIANT", "NOT_ABOUT_CAR"):
            gate[r.verdict.lower()] += 1
            outcome_by_url[p.url] = ("rejected", r.verdict.lower(), 0)
            return
        totals["docs"] += 1
        d = p.as_doc()
        if d.url in readings:
            a, rj = await persist_reading(ports, v, job.area, d, readings[d.url], known, values_rejected, p)
            totals["reader"] += a
        else:
            try:
                async with sem:
                    out = await ex.extract(ports.llm, ports.ref.prompts, job.area, target, d)
            except BudgetExceeded:
                raise
            except Exception:  # noqa: BLE001 - one failing source never fails the job
                return
            if out is None or not getattr(out, "is_about_variant", True):
                return
            uncertain = r.verdict in ("UNCERTAIN", "MULTI_VARIANT")
            async with sem:
                a, rj = await persist_extraction(ports, v, job.area, d, out, target, uncertain, p, known,
                                                 values_rejected, car_year=job.car_year)  # fmt: skip
        totals["accepted"] += a
        totals["rejected"] += rj
        outcome_by_url[p.url] = (
            ("accepted", None, a) if a else ("rejected", "values_rejected", 0) if rj else ("empty", None, 0)
        )

    await asyncio.gather(*(one(p) for p in pages))
    await _shadow_extracted(job.area, [p for p in pages if p.url not in readings and outcome_by_url.get(p.url)])
    await _record_registry(ports, job, pages, outcome_by_url, stats.get("url_market", {}))
    for k, n in gate.items():
        stats["pages_rejected"][k] = stats["pages_rejected"].get(k, 0) + n
    if gate:
        await emit("relevance", f"{job.area}: {sum(gate.values())} of {len(pages)} pages rejected (other variant)")
    accepted, rejected, reader_values = totals["accepted"], totals["rejected"], totals["reader"]
    stats["values_rejected"] = dict(values_rejected)
    stats["reader_values"] = reader_values
    if job.area in ex.SPEC_AREAS or job.area == "maintenance":
        await ValueSelection(ports.stores.values).reselect(v.id)
    hits = await area_hits(ports.stores.book, v, job.area)
    met = await _area_met(v, job.area, hits)
    await _mark_run(ports.stores.book, v.id, job, totals["docs"], accepted, rejected, met, registry=job.escalated)
    await _job_metrics(ports.stores.book, job.job_id, planned, stats)
    await emit("validating", f"{job.area}: {accepted} accepted, {rejected} rejected by validation")
    return JobResult(
        job.job_id,
        v.id,
        job.area,
        job.round,
        docs=totals["docs"],
        accepted=accepted,
        rejected=rejected,
        minimum_met=met,
        hits=hits,
    )


async def _run_market(ports: AcqPorts, job: JobSpec, emit: Emit) -> JobResult:
    """A market-level area (spec 006 US5): pages are about the market, not the car, so no relevance gate;
    every fact needs a verbatim excerpt with its amount and is stored once per market and key."""
    v = await variant(ports, job.variant_id)
    seen = await ports.stores.book.used_urls(v.id)
    planned, pages, stats = await pages_for(ports, v, job, [], seen, emit)
    await emit("reading", f"{job.area}: reading {len(pages)} sources")
    sem = asyncio.Semaphore(_llm_per_job(ports))
    totals = {"accepted": 0, "rejected": 0, "docs": 0}
    domains: dict[str, int] = defaultdict(int)

    async def one(p: Page) -> None:
        d = p.as_doc()
        try:
            async with sem:
                out = await ex.extract(ports.llm, ports.ref.prompts, job.area, "Spain (ES market)", d)
        except BudgetExceeded:
            raise
        except Exception:  # noqa: BLE001 - one failing source never fails the job
            return
        if out is None:
            return
        totals["docs"] += 1
        rows, rj = market.accept(out, d)
        a = 0
        if rows and ports.market_facts is not None:
            evidence_id = await ports.stores.evidence.save(evidence_in(v, d, p))
            a = await ports.market_facts.upsert(rows, evidence_id)
        totals["accepted"] += a
        totals["rejected"] += rj
        if a:
            domains[ev.domain_of(d.url)] += a

    await asyncio.gather(*(one(p) for p in pages))
    hits = [{"domain": dm, "source_type": "PUBLICATION", "items": n} for dm, n in domains.items()]
    met = research_plan.minimum_met(job.area, [research_plan.SourceHit(**h) for h in hits])
    await _mark_run(ports.stores.book, v.id, job, totals["docs"], totals["accepted"], totals["rejected"], met)
    await _job_metrics(ports.stores.book, job.job_id, planned, stats)
    await emit("validating", f"{job.area}: {totals['accepted']} accepted, {totals['rejected']} rejected")
    return JobResult(job.job_id, v.id, job.area, job.round, docs=totals["docs"], accepted=totals["accepted"],
                     rejected=totals["rejected"], minimum_met=met, hits=hits)  # fmt: skip


async def _job_metrics(book: JobBook, job_id: str, planned: list[search_plan.PlannedQuery],
                       stats: dict[str, Any]) -> None:  # fmt: skip
    empty = {(q.text, q.market) for q in stats.get("empty_queries", [])}
    queries = [{"text": q.text, "kind": q.kind, "market": q.market, "empty": (q.text, q.market) in empty}
               for q in planned]  # fmt: skip
    await book.record_metrics(job_id, JobMetrics(queries=queries, pages_found=stats["pages_found"],
                                                 pages_cached=stats["pages_cached"],
                                                 pages_rejected=stats["pages_rejected"],
                                                 values_rejected=stats.get("values_rejected") or None,
                                                 reader_values=int(stats.get("reader_values") or 0)))  # fmt: skip


async def area_hits(book: JobBook, v: VariantFacts, area: str) -> list[dict[str, Any]]:
    """Accepted evidence per source domain for an area (input to the section minimum); `unverified` marks a
    registry candidate's evidence (counts half, spec 011 FR-022). KeyError: an area with no store of its own."""
    return hits_of(await book.area_sources(v.id, v.make, area, source_kind(area, ex.SPEC_AREAS)))


async def _mark_run(book: JobBook, variant_id: str, job: JobSpec, docs: int, acc: int, rej: int, met: bool, *,
                    registry: bool = False) -> None:  # fmt: skip
    """`registry`: the job tried the registry's sources with the escalation to the other markets (kept otherwise)."""
    run = AreaRun(variant_id=variant_id, area=job.area, docs=docs, accepted=acc, rejected=rej, rounds=job.round,
                  minimum_met=met, registry=registry, stage_versions=STAGE_VERSIONS)  # fmt: skip
    await book.mark_run(run, brand_positioning=job.area == "manufacturer")


async def _area_met(v: VariantFacts, area: str, hits: list[dict[str, Any]]) -> bool:
    met = research_plan.minimum_met(area, [research_plan.SourceHit(**h) for h in hits])
    if met and area == "specs" and research_plan.energy_inputs_missing(v.powertrain, await _have(v.id)):
        return False  # spec 006 FR-009: look deeper for the energy inputs before "cannot be computed"
    return met
