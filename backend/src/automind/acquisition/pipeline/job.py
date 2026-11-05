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
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, select

from automind.acquisition.pipeline import extract as ex
from automind.acquisition.pipeline import fetch, locate, market, merge, parse, persist, plan, relevance, validate
from automind.acquisition.pipeline.locate import pages_for
from automind.acquisition.pipeline.merge import reselect
from automind.acquisition.pipeline.parse import _read_tables
from automind.acquisition.pipeline.persist import _evidence, _persist, _persist_reading
from automind.acquisition.pipeline.plan import _plan, _variant, current_plan, known_makes
from automind.acquisition.pipeline.relevance import _llm_per_job, _PageJudge, _relevance_target
from automind.acquisition.pipeline.validate import known_values
from automind.acquisition.read import _have, missing_critical
from automind.acquisition.registry.api import Attempt
from automind.application.ports import Page, Ports
from automind.application.usage import BudgetExceeded, current_job
from automind.domain import evidence as ev
from automind.domain import learned as learned_rules
from automind.domain import relevance as rel
from automind.domain import research_plan, search_plan
from automind.infrastructure import db

VERSION = "job@1"
# spec 011 FR-002: the versions of the stages a job ran, on every attempt and on the area's research run
_STAGES = (plan, locate, fetch, relevance, parse, validate, persist, merge, market)
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


def target_of(v: db.Variant, car_year: int | None = None) -> str:
    years = f" ({v.generation_years_from}–{v.generation_years_to or 'now'})" if v.generation_years_from else ""
    body = f", body {v.body_class.lower()}" if v.body_class else ""
    year = f", the user's car is from ~{car_year}" if car_year else ""
    return f"{v.label}{years}, powertrain {v.powertrain}{body}, market ES{year}"


async def _record_learned(ports: Ports, area: str, pages: list[Page], accepted_by_url: dict[str, int],
                          url_market: dict[str, str], independent: set[str] | None = None) -> None:  # fmt: skip
    """Only pages that came from a search count (never a pasted URL); `independent` are the URLs a normal (not
    learned) query also found (spec 007 J, T078)."""
    if ports.learned is None or not pages:
        return
    indep = independent if independent is not None else set(url_market)
    outcomes = [(learned_rules.domain_key(p.url), url_market[p.url], accepted_by_url.get(p.url, 0) > 0,
                 p.url in indep)
                for p in pages if p.url in url_market and not ev.is_denied(p.url)]  # fmt: skip
    try:
        await ports.learned.record(area, outcomes)
    except Exception:  # noqa: BLE001 - never fail a job over the hint table
        return


PageOutcome = tuple[str, str | None, int]  # (attempt outcome, reason, accepted values)


async def _record_registry(ports: Ports, job: JobSpec, pages: list[Page], outcome_by_url: dict[str, PageOutcome],
                           url_market: dict[str, str], independent: set[str] | None) -> None:  # fmt: skip
    """Every page read from a search is an attempt of its source for this kind of data (spec 010 FR-015)."""
    if ports.registry is None:
        return
    indep = independent if independent is not None else set(url_market)
    attempts = []
    for p in pages:
        if p.url not in url_market or ev.is_denied(p.url):
            continue
        outcome, reason, n = outcome_by_url.get(p.url, ("empty", None, 0))
        attempts.append(Attempt(area=job.area, market=url_market[p.url], url=p.url, snapshot_id=p.snapshot_id,
                                outcome=outcome, reason=reason, values=n, job_id=job.job_id,  # type: ignore[arg-type]
                                variant_id=job.variant_id, via_learned_query=p.url not in indep,
                                stage_versions=STAGE_VERSIONS))  # fmt: skip
    await ports.registry.record(attempts)


async def run_job(ports: Ports, job: JobSpec, emit: Emit) -> JobResult:
    token = current_job.set((job.job_id, job.area))
    plan_token = current_plan.set(await _plan(ports, job))
    count = ports.metrics or (lambda *a, **k: None)  # spec 010: Prometheus counters through the port
    try:
        result = await (_run_market if job.area in research_plan.MARKET_AREAS else _run)(ports, job, emit)
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
        current_plan.reset(plan_token)
        current_job.reset(token)


async def _run(ports: Ports, job: JobSpec, emit: Emit) -> JobResult:
    v = await _variant(job.variant_id)
    missing = await missing_critical(v.id, v.powertrain) if job.area == "specs" else []
    seen = await _used_urls(v.id, job.area)
    planned, pages, stats = await pages_for(ports, v, job, missing, seen, emit)
    target = target_of(v, job.car_year)
    # One pipeline per page (spec 004 FR-032): relevance → table reader or extraction → validation → storage.
    # Pages run concurrently; the model calls are bounded per job here and in total by the gateway.
    await emit("reading", f"{job.area}: reading {len(pages)} sources ({stats['pages_cached']} from cache)")
    tgt, gens = _relevance_target(v, ports)
    judge = _PageJudge(ports, v, tgt, gens, target, job.area)
    makes = known_makes(ports)
    sem = asyncio.Semaphore(_llm_per_job(ports))
    known = await known_values(v.id)
    readings = await _read_tables(ports, v, pages) if job.area in ex.SPEC_AREAS else {}
    gate: dict[str, int] = defaultdict(int)
    values_rejected: dict[str, int] = defaultdict(int)
    totals = {"accepted": 0, "rejected": 0, "reader": 0, "docs": 0}
    accepted_by_url: dict[str, int] = defaultdict(int)
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
            a, rj = await _persist_reading(ports, v, job.area, d, readings[d.url], known, values_rejected, p)
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
                a, rj = await _persist(ports, v, job.area, d, out, target, uncertain, p, known, values_rejected,
                                       car_year=job.car_year)  # fmt: skip
        totals["accepted"] += a
        totals["rejected"] += rj
        accepted_by_url[p.url] += a
        outcome_by_url[p.url] = (
            ("accepted", None, a) if a else ("rejected", "values_rejected", 0) if rj else ("empty", None, 0)
        )

    await asyncio.gather(*(one(p) for p in pages))
    await _record_learned(ports, job.area, pages, accepted_by_url, stats.get("url_market", {}),
                          stats.get("independent_urls"))  # fmt: skip
    await _record_registry(ports, job, pages, outcome_by_url, stats.get("url_market", {}),
                           stats.get("independent_urls"))  # fmt: skip
    for k, n in gate.items():
        stats["pages_rejected"][k] = stats["pages_rejected"].get(k, 0) + n
    if gate:
        await emit("relevance", f"{job.area}: {sum(gate.values())} of {len(pages)} pages rejected (other variant)")
    accepted, rejected, reader_values = totals["accepted"], totals["rejected"], totals["reader"]
    stats["values_rejected"] = dict(values_rejected)
    stats["reader_values"] = reader_values
    if job.area in ex.SPEC_AREAS or job.area == "maintenance":
        await reselect(v.id)
    hits = await area_hits(v, job.area)
    met = await _area_met(v, job.area, hits)
    await _mark_run(v.id, job.area, totals["docs"], accepted, rejected, job.round, met, registry=job.escalated)
    await _job_metrics(job.job_id, planned, stats)
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


async def _run_market(ports: Ports, job: JobSpec, emit: Emit) -> JobResult:
    """A market-level area (spec 006 US5): pages are about the market, not the car, so no relevance gate;
    every fact needs a verbatim excerpt with its amount and is stored once per market and key."""
    v = await _variant(job.variant_id)
    seen = await _used_urls(v.id, job.area)
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
            async with db.sessionmaker()() as s:
                e = await _evidence(s, v, d, p)
                await s.commit()
            a = await ports.market_facts.upsert(rows, e.id)
        totals["accepted"] += a
        totals["rejected"] += rj
        if a:
            domains[ev.domain_of(d.url)] += a

    await asyncio.gather(*(one(p) for p in pages))
    hits = [{"domain": dm, "source_type": "PUBLICATION", "items": n} for dm, n in domains.items()]
    met = research_plan.minimum_met(job.area, [research_plan.SourceHit(**h) for h in hits])
    await _mark_run(v.id, job.area, totals["docs"], totals["accepted"], totals["rejected"], job.round, met)
    await _job_metrics(job.job_id, planned, stats)
    await emit("validating", f"{job.area}: {totals['accepted']} accepted, {totals['rejected']} rejected")
    return JobResult(job.job_id, v.id, job.area, job.round, docs=totals["docs"], accepted=totals["accepted"],
                     rejected=totals["rejected"], minimum_met=met, hits=hits)  # fmt: skip


async def _job_metrics(job_id: str, planned: list[search_plan.PlannedQuery], stats: dict[str, Any]) -> None:
    async with db.sessionmaker()() as s:
        cost = (
            await s.execute(
                select(func.coalesce(func.sum(db.SearchCall.cost_eur), 0)).where(db.SearchCall.job_id == job_id)
            )
        ).scalar_one()
        job = await s.get(db.ResearchJob, job_id)
        if job is None:
            return
        empty = {(q.text, q.market) for q in stats.get("empty_queries", [])}
        job.queries = [{"text": q.text, "kind": q.kind, "market": q.market, "learned": q.learned,
                        "empty": (q.text, q.market) in empty} for q in planned]  # fmt: skip
        job.pages_found = stats["pages_found"]
        job.pages_cached = stats["pages_cached"]
        job.pages_rejected = {**(job.pages_rejected or {}), **stats["pages_rejected"]}
        job.search_cost_eur = float(cost)
        job.values_rejected = stats.get("values_rejected") or None
        job.reader_values = int(stats.get("reader_values") or 0)
        await s.commit()


async def _used_urls(variant_id: str, area: str) -> set[str]:
    async with db.sessionmaker()() as s:
        rows = await s.execute(
            select(db.Evidence.url)
            .join(db.Claim, db.Claim.evidence_id == db.Evidence.id, isouter=True)
            .where(db.Evidence.variant_id == variant_id)
        )
        return {str(u) for u in rows.scalars()}


async def _claim_sources(s: Any, v: db.Variant, area: str) -> list[tuple[str, str]]:
    q = (
        select(db.Evidence.domain, db.Evidence.source_type)
        .join(db.Claim, db.Claim.evidence_id == db.Evidence.id)
        .where(db.Claim.variant_id == v.id, db.Claim.area == area, db.Claim.status == "ACCEPTED")
    )
    return [(str(a), str(b)) for a, b in (await s.execute(q)).all()]


async def _maintenance_sources(s: Any, v: db.Variant) -> list[tuple[str, str]]:
    out = []
    rows = await s.execute(select(db.MaintenanceItem.evidence_ids).where(db.MaintenanceItem.variant_id == v.id))
    for (ids,) in rows.all():
        for eid in ids or []:
            e = await s.get(db.Evidence, eid)
            if e:
                out.append((e.domain, e.source_type))
    return out


async def _table_sources(s: Any, v: db.Variant, area: str) -> list[tuple[str, str]]:
    table: Any = {"reviews": db.ReviewItem, "reliability": db.Issue, "used_issues": db.Issue,
                  "used_price": db.UsedPriceRange, "depreciation": db.ValueRetention}[area]  # fmt: skip
    q = select(db.Evidence.domain, db.Evidence.source_type).join(table, table.evidence_id == db.Evidence.id)
    q = q.where(table.variant_id == v.id)
    if table is db.UsedPriceRange:
        q = q.where(db.UsedPriceRange.status == "ACCEPTED")
    if table is db.Issue:
        q = q.where(db.Issue.area == area)
    out = [(str(a), str(b)) for a, b in (await s.execute(q)).all()]
    if area == "reliability":
        q2 = (
            select(db.Evidence.domain, db.Evidence.source_type)
            .join(db.ReliabilityStat, db.ReliabilityStat.evidence_id == db.Evidence.id)
            .where(db.ReliabilityStat.variant_id == v.id)
        )
        out += [(str(a), str(b)) for a, b in (await s.execute(q2)).all()]
    return out


async def _manufacturer_sources(s: Any, v: db.Variant) -> list[tuple[str, str]]:
    rows = await s.execute(select(db.ManufacturerFact.url).where(db.ManufacturerFact.make == v.make))
    return [(ev.domain_of(u), ev.classify_source(u)) for (u,) in rows.all()]


async def area_hits(v: db.Variant, area: str) -> list[dict[str, Any]]:
    """Accepted evidence per source domain for an area (input to the section minimum)."""
    async with db.sessionmaker()() as s:
        if area in ex.SPEC_AREAS:
            pairs = await _claim_sources(s, v, area)
        elif area == "maintenance":
            pairs = await _claim_sources(s, v, area) + await _maintenance_sources(s, v)
        elif area == "manufacturer":
            pairs = await _manufacturer_sources(s, v)
        else:
            pairs = await _table_sources(s, v, area)
    counts: dict[tuple[str, str], int] = defaultdict(int)
    for p in pairs:
        counts[p] += 1
    return [{"domain": d, "source_type": t, "items": n} for (d, t), n in counts.items()]


async def _mark_run(variant_id: str, area: str, docs: int, acc: int, rej: int, round_: int, met: bool,
                    *, registry: bool = False) -> None:  # fmt: skip
    """`registry`: the job tried the registry's sources with the escalation to the other markets (kept otherwise)."""
    async with db.sessionmaker()() as s:
        old = await s.execute(
            select(db.ResearchRun.registry_at).where(db.ResearchRun.variant_id == variant_id,
                                                     db.ResearchRun.area == area)
        )  # fmt: skip
        tried = datetime.now(UTC) if registry else old.scalars().first()
        await s.execute(
            delete(db.ResearchRun).where(db.ResearchRun.variant_id == variant_id, db.ResearchRun.area == area)
        )
        s.add(
            db.ResearchRun(
                variant_id=variant_id,
                area=area,
                docs_used=docs,
                claims_accepted=acc,
                claims_rejected=rej,
                rounds_used=round_,
                minimum_met=met,
                registry_at=tried,
                stage_versions=STAGE_VERSIONS,
            )
        )
        if area == "manufacturer":
            await _brand_positioning(s, variant_id)
        await s.commit()


async def _brand_positioning(s: Any, variant_id: str) -> None:
    """Status indicator (FR-028): brand positioning only from sourced MARKET_POSITION facts."""
    v = await s.get(db.Variant, variant_id)
    if v is None:
        return
    rows = (
        await s.execute(
            select(db.ManufacturerFact.positioning).where(
                db.ManufacturerFact.make == v.make, db.ManufacturerFact.positioning.is_not(None)
            )
        )
    ).scalars()
    votes: dict[str, int] = defaultdict(int)
    for p in rows:
        votes[str(p)] += 1
    if votes:
        best = max(sorted(votes), key=lambda k: votes[k])
        for other in (await s.execute(select(db.Variant).where(db.Variant.make == v.make))).scalars():
            other.brand_positioning = best


async def _area_met(v: db.Variant, area: str, hits: list[dict[str, Any]]) -> bool:
    met = research_plan.minimum_met(area, [research_plan.SourceHit(**h) for h in hits])
    if met and area == "specs" and research_plan.energy_inputs_missing(v.powertrain, await _have(v.id)):
        return False  # spec 006 FR-009: look deeper for the energy inputs before "cannot be computed"
    return met
