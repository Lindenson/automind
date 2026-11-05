"""Research workers: one job = one car × one area (research R8, R14; FR-013..FR-023).

run_job: area queries (EN + ES) → search with full text → extraction (web reader, no tools) →
programmatic validation (verbatim excerpts, units, ranges) → validator role for pages whose variant
match is uncertain → persist evidence and items → recompute selected values → area freshness and
section minimum. One failing source never fails the job; one failing job never fails the turn.

Constitution I (evidence first), III (code normalizes numbers), VIII (untrusted content), XI (gates).
"""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import re
from collections import defaultdict
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy import delete, func, select, text

from automind.acquisition.pipeline import stamp
from automind.acquisition.pipeline.plan import (
    SITE_QUERY_PAGES,
    _ai_queries,
    _plan,
    _variant,
    identity_of,
    known_makes,
    learned_sites,
    market_names,
    queries_for,
    registry_queries,
)
from automind.acquisition.registry.api import Attempt, Plan
from automind.application import extraction as ex
from automind.application import incentives_research
from automind.application.ports import Page, Ports, WebDoc
from automind.application.usage import BudgetExceeded, current_job
from automind.domain import evidence as ev
from automind.domain import identity, plausibility, research_plan, search_plan, sense, sense_ev, specs, used
from automind.domain import learned as learned_rules
from automind.domain import relevance as rel
from automind.infrastructure import db

Emit = Callable[[str, str], Awaitable[None]]

CRITICAL = ("max_power", "max_torque", "curb_mass", "drivetrain", "claimed_0_100", "top_speed")
MAX_DOCS_PER_JOB = 8  # default; config/search.yaml limits.max_pages_per_job
NO_FAVOURITE = 9


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


MAX_LLM_RELEVANCE_PER_JOB = 4
SERVICE_AREAS = ("maintenance",)  # brand-wide service pages count (spec 009 FR-020); warranty is a BRAND_AREA


LLM_PER_JOB = 6  # default; config/search.yaml concurrency.llm_per_job


def _llm_per_job(ports: Ports) -> int:
    return int(((ports.ref.search or {}).get("concurrency") or {}).get("llm_per_job", LLM_PER_JOB))


def _relevance_target(v: db.Variant, ports: Ports) -> tuple[rel.Target, list[rel.GenerationInfo]]:
    gens = [rel.GenerationInfo(g, a, b) for g, a, b in ports.ref.generations.get(f"{v.make}|{v.model}", [])]
    if v.generation and not any(g.code == v.generation for g in gens):
        gens.append(rel.GenerationInfo(v.generation, v.generation_years_from, v.generation_years_to))
    tgt = rel.Target(v.make, v.model, v.generation, v.generation_years_from, v.generation_years_to,
                     v.variant_name, fuel_of(v.variant_name, v.powertrain), v.body_class,
                     v.transmission or _variant_gearbox(v), v.drive)  # fmt: skip
    return tgt, gens


class _PageJudge:
    """Relevance of one page: rules first, the relevance role for uncertain pages (at most
    MAX_LLM_RELEVANCE_PER_JOB per job). Safe to call concurrently: the budget is taken before any await."""

    def __init__(self, ports: Ports, v: db.Variant, tgt: rel.Target, gens: list[rel.GenerationInfo], target: str,
                 area: str | None = None):  # fmt: skip
        self.ports, self.v, self.tgt, self.gens, self.target = ports, v, tgt, gens, target
        self.service = area in SERVICE_AREAS
        self.llm_left = MAX_LLM_RELEVANCE_PER_JOB if "relevance" in ports.ref.prompts else 0

    async def __call__(self, p: Page) -> rel.Relevance:
        facts = rel.PageFacts(p.url, p.title, p.text)
        if self.service:  # spec 009 FR-020: the brand's service and warranty pages apply to the car
            r = rel.judge_service(facts, self.tgt, self.gens, known_makes(self.ports))
        else:
            r = rel.judge(facts, self.tgt, self.gens)
        method = "RULES"
        if r.verdict == "UNCERTAIN" and self.llm_left > 0:
            self.llm_left -= 1
            try:
                out = await ex.judge_relevance(
                    self.ports.llm, self.ports.ref.prompts["relevance"], self.target, p.as_doc()
                )
                r, method = rel.Relevance(out.verdict, out.reason or "relevance check", out.other), "LLM"
            except BudgetExceeded:
                raise
            except Exception:  # noqa: BLE001 - no answer: stays uncertain, the validator decides per claim
                pass
        await _store_relevance(p, self.v.id, r, method)
        return r


async def _store_relevance(p: Page, variant_id: str, r: rel.Relevance, method: str) -> None:
    if p.document_id is None:
        return
    from sqlalchemy.dialects.postgresql import insert  # noqa: PLC0415

    values = {"document_id": p.document_id, "variant_id": variant_id, "verdict": r.verdict,
              "other": (r.other or "")[:80] or None, "reason": r.reason, **stamp.relevance(method)}  # fmt: skip
    async with db.sessionmaker()() as s:
        stmt = insert(db.PageRelevance).values(**values)
        await s.execute(stmt.on_conflict_do_update(index_elements=["document_id", "variant_id"], set_=values))
        await s.commit()


def fuel_of(variant_name: str, powertrain: str | None) -> str | None:
    if (powertrain or "").upper() == "BEV":
        return "electric"
    n = f" {variant_name.lower()} "
    diesel = (" d ", "tdi", "dci", "cdi", "d-4d", "hdi", "crdi", "diesel", "jtd", "multijet", "tdci", "bluehdi",
              "skyactiv-d", "i-dtec", "ecoblue")  # fmt: skip
    if any(k in n for k in diesel) or re_diesel_suffix(n):
        return "diesel"
    return "petrol"


def re_diesel_suffix(n: str) -> bool:
    return re.search(r"\b\d{3}d\b|\b\d\.\dd\b|\b\d{3} d\b", n) is not None  # 520d, 2.0d, E 220 d


async def _known_values(variant_id: str) -> dict[str, float]:
    async with db.sessionmaker()() as s:
        rows = await s.execute(
            select(db.SpecValue.attribute, db.SpecValue.value_num).where(
                db.SpecValue.variant_id == variant_id, db.SpecValue.available, db.SpecValue.value_num.is_not(None)
            )
        )
        return {a: float(n) for a, n in rows.all()}


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


# spec 010 US6-US8: the registry's plan for the running job (source order and the domains never to read)
current_plan: ContextVar[Plan | None] = ContextVar("current_plan", default=None)


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
                                variant_id=job.variant_id, via_learned_query=p.url not in indep))  # fmt: skip
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
    planned, pages, stats = await _search_pages(ports, v, job, missing, seen, emit)
    target = target_of(v, job.car_year)
    # One pipeline per page (spec 004 FR-032): relevance → table reader or extraction → validation → storage.
    # Pages run concurrently; the model calls are bounded per job here and in total by the gateway.
    await emit("reading", f"{job.area}: reading {len(pages)} sources ({stats['pages_cached']} from cache)")
    tgt, gens = _relevance_target(v, ports)
    judge = _PageJudge(ports, v, tgt, gens, target, job.area)
    makes = known_makes(ports)
    sem = asyncio.Semaphore(_llm_per_job(ports))
    known = await _known_values(v.id)
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
    planned, pages, stats = await _search_pages(ports, v, job, [], seen, emit)
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
        rows, rj = incentives_research.accept(out, d)
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


def favourite_priority(ports: Ports, v: db.Variant | None, url: str) -> int | None:
    """Priority of the favourite (or official manufacturer site) the URL belongs to, else None. With registry
    autonomy on, the registry's order replaces the configured favourites (spec 010 US6)."""
    dom = ev.domain_of(url)
    plan = current_plan.get()
    full = dom + "/" + url.split(dom, 1)[-1].lstrip("/") if dom in url else dom
    if v is not None and (m := ports.ref.manufacturer_sites.get(v.make)):
        host = m.split("/")[0].removeprefix("www.")
        if dom == host or dom.endswith("." + host):  # the host itself (never toyota.es.example.com)
            return 0
    if plan is not None and plan.autonomy:
        p = plan.priority_of(dom)
        return None if p is None else p + 1
    best = None
    for f in ports.ref.favourites:
        d = str(f["domain"])
        if dom == d or dom.endswith("." + d) or full.startswith(d):
            p = int(f.get("priority", 3))
            best = p if best is None else min(best, p)
    return best


def _skipped(url: str) -> bool:
    """Blocked in the registry (classifieds, terms forbid, robots): never read (spec 010 US7 hard limits)."""
    plan = current_plan.get()
    if plan is None or not plan.skip:
        return False
    d = ev.domain_of(url)
    return any(d == x or d.endswith("." + x) for x in plan.skip)


WARRANTY_PAGES = 3  # pages read for the brand's warranty terms in round 0 of the manufacturer area


def _rank_hits(
    ports: Ports, v: db.Variant | None, planned: list[search_plan.PlannedQuery], results: list[Any], seen: set[str]
) -> tuple[dict[str, tuple[int, int, int]], dict[str, str], list[search_plan.PlannedQuery], int, set[str]]:
    """Favourites first, then by authority and rank; also which market found a URL, which queries were empty and
    which URLs a normal (not learned) query found."""
    from automind.application.usage import BudgetExceeded as _BE  # noqa: PLC0415

    ranked: dict[str, tuple[int, int, int]] = {}
    url_market: dict[str, str] = {}
    empty: list[search_plan.PlannedQuery] = []
    failures = 0
    independent: set[str] = set()  # found by a normal (not learned) query
    for q, r in zip(planned, results, strict=True):
        if isinstance(r, _BE):
            raise r
        if isinstance(r, BaseException):
            failures += 1
            continue
        if not r:
            empty.append(q)
        for h in r:
            url_market.setdefault(h.url, q.market)
            if not getattr(q, "learned", False):
                independent.add(h.url)
            if h.url in seen or ev.is_denied(h.url) or _skipped(h.url):
                continue
            fav = favourite_priority(ports, v, h.url)
            key = (NO_FAVOURITE if fav is None else fav, ev.AUTHORITY.index(ev.classify_source(h.url)), h.rank)
            ranked[h.url] = min(ranked.get(h.url, key), key)
    return ranked, url_market, empty, failures, independent


async def _collect(
    ports: Ports,
    planned: list[search_plan.PlannedQuery],
    seen: set[str],
    area: str,
    v: db.Variant | None = None,
    *,
    fresh: bool = False,
    limit: int | None = None,
) -> tuple[list[Page], dict[str, Any]]:
    """Search (cache-first) → rank favourites first → fetch pages through the page store (R2–R4)."""
    from automind.application.usage import BudgetExceeded as _BE  # noqa: PLC0415

    results = await asyncio.gather(
        *(ports.search.search(q.text, market=q.market, area=area, fresh=fresh) for q in planned),
        return_exceptions=True,
    )
    ranked, url_market, empty, failures, independent = _rank_hits(ports, v, planned, results, seen)
    order = sorted(ranked, key=lambda u: ranked[u])
    limit = limit or int(((ports.ref.search or {}).get("limits") or {}).get("max_pages_per_job", MAX_DOCS_PER_JOB))
    store = ports.page_store
    pages: list[Page] = []
    rejected: dict[str, int] = defaultdict(int)
    pos = 0
    while len(pages) < limit and pos < len(order) and pos < 2 * limit:
        batch = order[pos : pos + (limit - len(pages))]
        pos += len(batch)
        got = await asyncio.gather(*(store.get(u, area=area) for u in batch), return_exceptions=True)
        for u, g in zip(batch, got, strict=True):
            if isinstance(g, _BE):
                raise g
            if isinstance(g, Page):
                pages.append(g)
            else:
                reason = store.last_reason(u) if not isinstance(g, BaseException) else type(g).__name__
                rejected[_reason_key(reason)] += 1
    stats = {
        "pages_found": len(ranked),
        "pages_cached": sum(1 for p in pages if p.from_cache),
        "pages_rejected": dict(rejected),
        "search_failures": failures,
        "url_market": url_market,
        "empty_queries": empty,
        "independent_urls": independent,
    }
    return pages, stats


async def _search_pages(
    ports: Ports, v: db.Variant, job: JobSpec, missing: list[str], seen: set[str], emit: Emit
) -> tuple[list[search_plan.PlannedQuery], list[Page], dict[str, Any]]:
    planned = queries_for(ports, v, job.area, job.round, missing,
                          await learned_sites(ports, job.area) if job.round == 0 else None, job.car_year)  # fmt: skip
    if job.fresh and job.round == 0:  # search again: favourites and the open web together, past the cache
        more = queries_for(ports, v, job.area, 1, missing, car_year=job.car_year)
        planned += [q for q in more if q.text not in {p.text for p in planned}]
    warranty = search_plan.warranty_query(planned, job.area, job.round, identity_of(v), ports.ref.favourite_queries)
    await emit(
        "searching", f"{job.area}: {len(planned) + len(warranty)} searches" + (" (follow-up)" if job.round else "")
    )
    pages, stats = await _collect(ports, planned, seen, job.area, v, fresh=job.fresh)
    if warranty:  # spec 008 FR-027: its own few pages, so blocked analyst sites ranked first cannot crowd it out
        more, more_stats = await _collect(ports, warranty, seen | {p.url for p in pages}, job.area, v,
                                          fresh=job.fresh, limit=WARRANTY_PAGES)  # fmt: skip
        pages += more
        planned += warranty
        stats = _merge_stats(stats, more_stats)
    retry_on = bool((ports.ref.search or {}).get("favourite_retry", True))
    retry = search_plan.retry_queries(stats["empty_queries"], identity_of(v), ports.ref.favourite_queries,
                                      market_names(ports, v))  # fmt: skip
    if retry_on and retry:  # a favourite query found nothing: once more, shorter (spec 007 FR-021)
        await emit("searching", f"{job.area}: {len(retry)} shorter searches")
        more, more_stats = await _collect(ports, retry, seen | {p.url for p in pages}, job.area, v)
        pages += more
        planned += retry
        stats = _merge_stats(stats, more_stats)
    site = await registry_queries(ports, v, job, planned)
    if site:  # spec 010: the registry's sources, with their own few pages so the favourites cannot crowd them out
        await emit("searching", f"{job.area}: {len(site)} searches on registered sources")
        limit = int((ports.ref.registry or {}).get("site_query_pages_per_job", SITE_QUERY_PAGES))
        more, more_stats = await _collect(ports, site, seen | {p.url for p in pages}, job.area, v,
                                          fresh=job.fresh, limit=limit)  # fmt: skip
        pages += more
        planned += site
        stats = _merge_stats(stats, more_stats)
    if job.round > 0 and len(pages) < 2:  # open web found too little: bounded AI-proposed queries (FR-004)
        extra = await _ai_queries(ports, v, job.area, missing, [q.text for q in planned])
        if extra:
            await emit("searching", f"{job.area}: {len(extra)} more searches suggested by the assistant")
            more, more_stats = await _collect(ports, extra, seen | {p.url for p in pages}, job.area, v)
            pages += more
            planned += extra
            stats = _merge_stats(stats, more_stats)
    return planned, pages, stats


async def _read_tables(ports: Ports, v: db.Variant, pages: list[Page]) -> dict[str, Any]:
    """Deterministic site readers for favourite spec sites; ambiguous or unknown layouts go to the LLM."""
    readings: dict[str, Any] = {}
    for p in pages:
        r = ports.readers.read(p, {"variant_id": v.id})
        if r is not None and not r.ambiguous:
            readings[p.url] = r
    flush = getattr(ports.readers, "flush_stats", None)
    if flush is not None:
        await flush()
    return readings


def _merge_stats(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    rej = dict(a["pages_rejected"])
    for k, n in b["pages_rejected"].items():
        rej[k] = rej.get(k, 0) + n
    return {
        "pages_found": a["pages_found"] + b["pages_found"],
        "pages_cached": a["pages_cached"] + b["pages_cached"],
        "pages_rejected": rej,
        "search_failures": a["search_failures"] + b["search_failures"],
        "url_market": {**b.get("url_market", {}), **a.get("url_market", {})},
        "empty_queries": [*a.get("empty_queries", []), *b.get("empty_queries", [])],
        "independent_urls": set(a.get("independent_urls", ())) | set(b.get("independent_urls", ())),
    }


def _reason_key(reason: str | None) -> str:
    r = (reason or "error").lower()
    for k in ("deny-list", "robots", "no content", "content type", "larger than", "http 4", "http 5"):
        if k in r:
            return k.replace(" ", "_")
    return "fetch_error"


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


async def _evidence(s: Any, v: db.Variant, d: WebDoc, page: Page | None = None, fav: int | None = None) -> db.Evidence:
    doc_id = page.document_id if page is not None else None
    if doc_id is None:
        sha = hashlib.sha256(d.text.encode()).hexdigest()
        doc = (
            await s.execute(select(db.Document).where(db.Document.content_sha256 == sha).limit(1))
        ).scalar_one_or_none()
        if doc is None:
            doc = db.Document(url=d.url, title=d.title, text=d.text, content_sha256=sha)
            s.add(doc)
            await s.flush()
        doc_id = doc.id
    e = db.Evidence(
        variant_id=v.id,
        document_id=doc_id,
        favourite=fav is not None,
        favourite_priority=fav,
        url=d.url,
        source_name=d.title[:200],
        domain=ev.domain_of(d.url),
        source_type=ev.classify_source(d.url),
        snippet_only=d.snippet_only,
    )
    s.add(e)
    await s.flush()
    return e


async def _persist(
    ports: Ports,
    v: db.Variant,
    area: str,
    d: WebDoc,
    out: BaseModel,
    target: str,
    uncertain: bool,
    page: Page | None = None,
    known: dict[str, float] | None = None,
    values_rejected: dict[str, int] | None = None,
    *,
    car_year: int | None = None,
) -> tuple[int, int]:
    async with db.sessionmaker()() as s:
        e = await _evidence(s, v, d, page, favourite_priority(ports, v, d.url))
        if area in ex.SPEC_AREAS:
            a, r = await _spec_claims(ports, s, v, area, d, e, out, target, uncertain, known or {},
                                      values_rejected if values_rejected is not None else defaultdict(int))  # fmt: skip
        else:
            rates = {k: float(x) for k, x in (ports.ref.feasibility.get("currency_to_eur") or {}).items()}
            a, r = await _items(s, v, area, d, e, out, rates, car_year=car_year)
        await s.commit()
    return a, r


def _plausibility_ctx(v: db.Variant, known: dict[str, float]) -> plausibility.Context:
    return plausibility.Context(
        powertrain=v.powertrain, fuel=fuel_of(v.variant_name, v.powertrain), known=known,
        transmission=v.transmission or _variant_gearbox(v), drive=v.drive,
    )  # fmt: skip


def _variant_gearbox(v: db.Variant) -> str | None:
    """The gearbox named in the variant name ("… 6AT", "… manual", "… e-CVT"), when the column is empty."""
    name = f" {v.variant_name} ".lower()
    if re.search(r"\b\d\s?(at|a/t)\b|automatic|automático|automatica", name):
        return "automatic"
    if re.search(r"\b\d\s?(mt|m/t)\b", name) or sense.says_manual(name):
        return "manual"
    return sense.gearbox_family(name)


MONEY_ATTRS = ("official_price_es",)


def _check(
    c: Any,
    d: WebDoc,
    ctx: plausibility.Context | None = None,
    rules: dict[str, Any] | None = None,
    *,
    excerpt_checked: bool = False,
) -> tuple[str, float | None, str | None, str | None]:
    """(status, number, text, reject_rule): excerpt → unit → plausibility (FR-014) → sense (004 FR-027)."""
    if (
        not excerpt_checked
        and specs.RANGE_RE.search(c.raw_value) is None
        and not ev.validate_excerpt(c.excerpt, c.raw_value, d.text)
    ):
        return "REJECTED_UNSUPPORTED", None, None, None
    if c.attribute in MONEY_ATTRS and not (r := sense.money_marked(c.raw_value, c.excerpt)).ok:
        return "REJECTED_IMPLAUSIBLE", None, None, r.rule_id  # a number without a currency is not a price
    try:
        val = specs.normalize(specs.ATTRS[c.attribute], c.raw_value, c.unit, excerpt=c.excerpt, domain=d.url)
    except Exception:
        return "REJECTED_UNIT", None, None, None
    if ctx is not None and rules:
        p = plausibility.check(c.attribute, val, ctx, rules)
        if not p.ok:
            return "REJECTED_IMPLAUSIBLE", None, None, p.rule_id
    if ctx is not None:
        bad = _sense_after(c.attribute, val, ctx)
        if bad is not None:
            return bad
    return ("ACCEPTED", val, None, None) if isinstance(val, float) else ("ACCEPTED", None, str(val), None)


def _litres(raw: str) -> float | None:
    """ "611", "1.642" (Spanish thousands) or "611 l" as litres; None when there is no number."""
    m = re.search(r"\d[\d.,\u202f ]*", raw or "")
    if not m:
        return None
    digits = (
        re.sub(r"[.,\u202f ]", "", m.group(0)) if re.fullmatch(r"\d{1,2}[.,]\d{3}", m.group(0).strip()) else m.group(0)
    )
    try:
        return float(digits.strip().replace(",", "."))
    except ValueError:
        return None


def _sense_before(
    c: Any, v: db.Variant, source_type: str | None, url: str = ""
) -> tuple[Any, tuple[str, None, None, str] | None]:
    """Re-file a claim under the attribute its value really is (WLTP / NEDC / real-world consumption); a boot
    volume with the seats folded, or of another body style, is not the boot volume."""
    if c.attribute == "boot_volume" and not (b := sense.boot_seats_up(c.raw_value, c.excerpt)).ok:
        return c, ("REJECTED_IMPLAUSIBLE", None, None, b.rule_id or "sense.boot")
    if c.attribute == "boot_volume" and not (b := sense.boot_fits_body(_litres(c.raw_value), v.body_class, url)).ok:
        return c, ("REJECTED_IMPLAUSIBLE", None, None, b.rule_id or "sense.boot")
    if (v.powertrain or "").upper() in sense_ev.PLUG_IN or c.attribute in _EV_CLAIMS:
        return _sense_ev_before(c, v)
    if c.attribute != "consumption":
        return c, None
    r = sense.classify_consumption(c.raw_value, c.excerpt, v.generation_years_from, source_type)
    if not r.ok:
        return c, ("REJECTED_IMPLAUSIBLE", None, None, r.rule_id or "sense.consumption")
    return _refile(c, r.attribute, r.value), None


_EV_CLAIMS = ("battery_kwh", "battery_gross_kwh", "charge_ac_kw", "charge_dc_peak_kw", "charge_dc_10_80_min",
              *sense_ev.EV_ATTRS, "consumption_cs", "consumption_weighted")  # fmt: skip


def _refile(c: Any, attribute: str | None, raw_value: Any) -> Any:
    update = {"attribute": attribute, "raw_value": raw_value}
    return c.model_copy(update=update) if hasattr(c, "model_copy") else dataclasses.replace(c, **update)


def _sense_ev_before(c: Any, v: db.Variant) -> tuple[Any, tuple[str, None, None, str] | None]:
    """Electric values (spec 006 R4): a plug-in's consumption by its words; gross vs usable; kWh vs kW."""
    plug_in = (v.powertrain or "").upper() in sense_ev.PLUG_IN
    if plug_in and c.attribute in (*sense_ev.FUEL_ATTRS, *sense_ev.EV_ATTRS):
        r = sense_ev.plug_in_consumption(c.attribute, c.raw_value, c.unit, c.excerpt)
        if not r.ok:
            return c, ("REJECTED_IMPLAUSIBLE", None, None, r.rule_id or "sense.phev")
        c = _refile(c, r.attribute, r.value)
    elif c.attribute in ("consumption_cs", "consumption_weighted"):  # only plug-ins have these
        return c, ("REJECTED_IMPLAUSIBLE", None, None, "sense.phev.not_plug_in")
    if c.attribute in ("battery_kwh", "battery_gross_kwh"):
        c = _refile(c, sense_ev.battery_kind(c.raw_value, c.excerpt), c.raw_value)
    r = sense_ev.check_claim(c.attribute, c.raw_value, c.unit, c.excerpt)
    if not r.ok:
        return c, ("REJECTED_IMPLAUSIBLE", None, None, r.rule_id or "sense.ev")
    return c, None


def _sense_after(attribute: str, val: Any, ctx: plausibility.Context) -> tuple[str, None, None, str] | None:
    """Meaning rules on a normalised value: gear counts of e-CVTs, another gearbox or drive than the variant."""
    if attribute == "gear_count" and isinstance(val, float):
        r = sense.gear_count(val, ctx.transmission, ctx.powertrain)
        if not r.ok:
            return "REJECTED_IMPLAUSIBLE", None, None, r.rule_id or "sense.gear_count"
    if attribute == "transmission" and sense.gearbox_conflict(ctx.transmission, str(val)):
        return "REJECTED_OTHER_VARIANT", None, None, "sense.transmission.other_gearbox"
    if attribute == "drivetrain" and sense.drive_conflict(ctx.drive, str(val)):
        return "REJECTED_OTHER_VARIANT", None, None, "sense.drivetrain.other_drive"
    if isinstance(val, float) and not (p := sense_ev.pair_check(attribute, val, ctx.known)).ok:
        return "REJECTED_IMPLAUSIBLE", None, None, p.rule_id or "sense.ev"
    return None


VALIDATOR_REJECTS = ("OTHER_VARIANT", "OTHER_MARKET", "OTHER_YEAR", "UNCLEAR")


async def _spec_claims(
    ports: Ports,
    s: Any,
    v: db.Variant,
    area: str,
    d: WebDoc,
    e: db.Evidence,
    out: Any,
    target: str,
    uncertain: bool,
    known: dict[str, float],
    values_rejected: dict[str, int],
) -> tuple[int, int]:
    ctx = _plausibility_ctx(v, known)
    checked = []
    for c0 in out.claims:
        c, bad = _sense_before(c0, v, ev.classify_source(d.url), d.url)
        checked.append((c, *(bad or _check(c, d, ctx, ports.ref.plausibility))))
    conflicting = {
        i for i, (c, st, num, _, _) in enumerate(checked)
        if st == "ACCEPTED" and num is not None and c.attribute in known
        and abs(num - known[c.attribute]) > max(abs(known[c.attribute]) * 0.06, 1e-9)
    }  # fmt: skip
    verdicts: dict[int, str] = {}
    if (uncertain or conflicting) and any(st == "ACCEPTED" for _, st, *_ in checked):
        verdicts = await ex.validate_claims(
            ports.llm,
            ports.ref.prompts["validator"],
            target,
            d,
            [{"label": c.attribute, "value": c.raw_value, "excerpt": c.excerpt} for c, *_ in checked],
        )
        if not uncertain:  # only the conflicting claims were in question
            verdicts = {i: verdicts[i] for i in conflicting if i in verdicts}
    accepted = rejected = 0
    market = sense.market_fits(d.url, area)
    for i, (c, status, num, txt, rule) in enumerate(checked):
        if status == "ACCEPTED" and not market.ok and c.attribute in ("official_price_es",):
            status, rule = "REJECTED_OTHER_MARKET", market.rule_id
        scope = "GENERATION" if d.snippet_only and c.scope == "VARIANT" else c.scope
        verdict = verdicts.get(i)
        if status == "ACCEPTED" and verdict in VALIDATOR_REJECTS:
            status = f"REJECTED_{verdict}"
        elif status == "ACCEPTED" and verdict == "GENERATION_WIDE":
            scope = "GENERATION"  # kept, but LOW confidence (FR-018)
        if status == "ACCEPTED":
            accepted += 1
        else:
            rejected += 1
            values_rejected[status.removeprefix("REJECTED_").lower()] += 1
        s.add(
            db.Claim(
                variant_id=v.id, evidence_id=e.id, attribute=c.attribute, area=area, raw_value=c.raw_value,
                raw_unit=c.unit, value_num=num, value_text=txt, excerpt=c.excerpt, scope=scope,
                provenance=ev.assign_provenance(e.source_type, c.attribute), status=status, reject_rule=rule,
                extracted_by="LLM", **stamp.extractor(d),
            )
        )  # fmt: skip
    return accepted, rejected


@dataclass
class _ReaderClaim:
    attribute: str
    raw_value: str
    unit: str | None
    excerpt: str


async def _persist_reading(
    ports: Ports,
    v: db.Variant,
    area: str,
    d: WebDoc,
    reading: Any,
    known: dict[str, float],
    values_rejected: dict[str, int],
    page: Page | None,
) -> tuple[int, int]:
    """Values read from a favourite site's table without AI (FR-009, FR-010): same provenance and checks
    (unit layer, plausibility); the excerpt is the table row the reader read."""
    ctx = _plausibility_ctx(v, known)
    accepted = rejected = 0
    async with db.sessionmaker()() as s:
        e = await _evidence(s, v, d, page, favourite_priority(ports, v, d.url))
        for row in reading.rows:
            if row.attribute not in specs.ATTRS:
                continue
            c, bad = _sense_before(
                _ReaderClaim(row.attribute, row.raw_value, row.raw_unit, row.excerpt),
                v,
                ev.classify_source(d.url),
                d.url,
            )
            status, num, txt, rule = bad or _check(c, d, ctx, ports.ref.plausibility, excerpt_checked=True)
            if status == "ACCEPTED":
                accepted += 1
            else:
                rejected += 1
                values_rejected[status.removeprefix("REJECTED_").lower()] += 1
            s.add(
                db.Claim(
                    variant_id=v.id, evidence_id=e.id, attribute=c.attribute, area=area, raw_value=c.raw_value,
                    raw_unit=c.unit, value_num=num, value_text=txt, excerpt=c.excerpt, scope="VARIANT",
                    provenance=ev.assign_provenance(e.source_type, c.attribute), status=status, reject_rule=rule,
                    extracted_by="READER", **stamp.reader(reading, page),
                )
            )  # fmt: skip
        await s.commit()
    return accepted, rejected


class _Counter:
    """Counts excerpt checks for one document."""

    def __init__(self, doc_text: str) -> None:
        self.doc_text, self.accepted, self.rejected = doc_text, 0, 0

    def ok(self, excerpt: str, must: str | None = None) -> bool:
        good = ex.excerpt_in_doc(excerpt, self.doc_text, must)
        self.accepted += good
        self.rejected += not good
        return good


def _maintenance(s: Any, v: db.Variant, e: db.Evidence, out: Any, k: _Counter) -> None:
    for it in out.items:
        if k.ok(it.excerpt):
            s.add(
                db.MaintenanceItem(
                    variant_id=v.id,
                    item=it.item[:200],
                    interval_km=interval_km(it.interval_km),
                    interval_months=interval_months(it.interval_months, it.excerpt),
                    cost_eur=_num(it.cost_eur),
                    cost_basis="SOURCED",
                    evidence_ids=[e.id],
                    excerpt=it.excerpt,
                )
            )


def interval_km(raw: str | None) -> int | None:
    """Service interval in km (sense rule: "16" next to "thousand km" is 16,000 km)."""
    return sense.interval_km(_int(raw))


def interval_months(raw: str | None, excerpt: str = "") -> int | None:
    """Interval in months (sense rule: "every 5 years" extracted as 5 is 60 months)."""
    return sense.interval_months(_int(raw), excerpt)


def _reviews(s: Any, v: db.Variant, e: db.Evidence, out: Any, k: _Counter) -> None:
    for it in out.items:
        if k.ok(it.excerpt):
            s.add(
                db.ReviewItem(
                    variant_id=v.id,
                    polarity=it.polarity,
                    tag=it.tag,
                    reviewer=it.reviewer,
                    text=it.text[:300],
                    excerpt=it.excerpt,
                    evidence_id=e.id,
                )
            )


def _issues(s: Any, v: db.Variant, area: str, e: db.Evidence, out: Any, k: _Counter) -> None:
    for it in out.issues:
        if k.ok(it.excerpt):
            s.add(
                db.Issue(
                    variant_id=v.id,
                    component=it.component[:120],
                    description=it.description,
                    age_from=it.age_from,
                    age_to=it.age_to,
                    mileage_from=it.mileage_from,
                    mileage_to=it.mileage_to,
                    severity_hint=it.severity_hint,
                    excerpt=it.excerpt,
                    area=area,
                    evidence_id=e.id,
                )
            )
    for st in out.stats:
        if k.ok(st.excerpt, st.value):
            s.add(
                db.ReliabilityStat(
                    variant_id=v.id,
                    source=st.source[:120],
                    metric=st.metric,
                    value=st.value[:80],
                    year=st.year,
                    excerpt=st.excerpt,
                    evidence_id=e.id,
                )
            )


def _brand_fact_ok(f: Any) -> tuple[bool, float | None]:
    """Spec 006 US6: a network count only next to a network word, a warranty only with plausible years."""
    number = getattr(f, "value_num", None)
    if f.fact_type == "NETWORK_ES":
        r = sense_ev.count_context(number, f.excerpt)
        return r.ok, r.value
    if f.fact_type in ("WARRANTY", "BATTERY_WARRANTY"):
        r = sense_ev.warranty_check(f.fact_type, f.excerpt)
        return r.ok, (r.value or {}).get("years")
    return True, number


def _manufacturer(s: Any, v: db.Variant, d: WebDoc, out: Any, k: _Counter) -> None:
    for f in out.facts:
        fits, number = _brand_fact_ok(f)
        if not fits:
            k.rejected += 1
            continue
        if k.ok(f.excerpt, must=f"{number:g}" if number is not None else None):
            s.add(
                db.ManufacturerFact(
                    make=v.make,
                    fact_type=f.fact_type,
                    text=f.text,
                    positioning=f.positioning if f.fact_type == "MARKET_POSITION" else None,
                    value_num=number,
                    year=getattr(f, "year", None),
                    excerpt=f.excerpt,
                    url=d.url,
                    source_name=d.title[:200],
                )
            )


async def _items(
    s: Any,
    v: db.Variant,
    area: str,
    d: WebDoc,
    e: db.Evidence,
    out: Any,
    rates: dict[str, float] | None = None,
    *,
    car_year: int | None = None,
) -> tuple[int, int]:
    """Non-numeric areas: keep only items whose excerpt literally occurs in the document."""
    k = _Counter(d.text)
    if area == "maintenance" and not sense.market_fits(d.url, area).ok:
        return 0, len(getattr(out, "items", []) or [])  # another market's schedule (e.g. Malaysia): not used
    if area == "maintenance":
        _maintenance(s, v, e, out, k)
    elif area == "reviews":
        _reviews(s, v, e, out, k)
    elif area in ("reliability", "used_issues"):
        _issues(s, v, area, e, out, k)
    elif area == "manufacturer":
        _manufacturer(s, v, d, out, k)
    elif area == "used_price":
        _used_prices(s, v, e, out, k, ports_rates=rates or {"EUR": 1.0}, car_year=car_year)
    elif area == "depreciation":
        _retention(s, v, e, out, k)
    return k.accepted, k.rejected


def _retention(s: Any, v: db.Variant, e: db.Evidence, out: Any, k: _Counter) -> None:
    """Residual values (spec 004 FR-005): verbatim excerpt with the number, 1–10 years, 5–100% left."""
    for p in out.points:
        share = float(p.share_pct) / 100 if p.share_pct is not None else None
        number = p.share_pct if p.share_pct is not None else p.eur
        if number is None or not 1 <= int(p.years) <= 10 or (share is not None and not 0.05 <= share <= 1.0):
            k.rejected += 1
            continue
        if not k.ok(p.excerpt, must=f"{number:g}" if share is None else None):
            continue
        s.add(
            db.ValueRetention(
                variant_id=v.id, evidence_id=e.id, years=int(p.years), share=share,
                eur=float(p.eur) if share is None and p.eur else None, market=p.market,
                quoted_on=_date(p.quoted_on), basis="SOURCED", excerpt=p.excerpt[:600],
            )
        )  # fmt: skip


USED_RANGE_MAX_RATIO = 1.6  # a used-price range wider than this (max / min) is a whole-market spread, not a price


def _used_prices(s: Any, v: db.Variant, e: db.Evidence, out: Any, k: _Counter, ports_rates: dict[str, float],
                 car_year: int | None = None) -> None:  # fmt: skip
    """Editorial used-price ranges (FR-022): verbatim excerpt containing the price, plausible numbers, EUR. For a car
    with a model year, a range over several model years (a whole generation) is rejected: it never stands for one
    year (seeded issue, chat 8c6a2a58)."""
    for r in out.ranges:
        lo, hi = sorted((float(r.min), float(r.max)))
        rate = ports_rates.get(r.currency, 1.0)
        # chat fcf5b3b8: "21 100 € – 93 520 €" for every Land Cruiser of a year is a market spread, not a price
        plausible = 500 <= lo * rate <= hi * rate <= 600_000 and hi <= USED_RANGE_MAX_RATIO * lo
        whole = used.whole_generation(r.model_year_from, r.model_year_to, car_year)
        good = not whole and k.ok(r.excerpt) and plausible
        if whole:
            k.rejected += 1
        s.add(
            db.UsedPriceRange(
                variant_id=v.id, evidence_id=e.id, model_year_from=r.model_year_from, model_year_to=r.model_year_to,
                min_eur=round(lo * rate), max_eur=round(hi * rate), market=r.market,
                quoted_on=_date(r.quoted_on), excerpt=r.excerpt[:300],
                status="ACCEPTED" if good else "REJECTED_OTHER_YEAR" if whole else (
                    "REJECTED_IMPLAUSIBLE" if not plausible else "REJECTED_UNSUPPORTED"),
            )
        )  # fmt: skip


def _date(raw: str | None) -> Any:
    from datetime import date  # noqa: PLC0415

    try:
        return date.fromisoformat(raw) if raw else None
    except ValueError:
        return None


def _num(raw: str | None) -> float | None:
    if not raw:
        return None
    try:
        from automind.domain import units

        return units.parse_number(raw)
    except Exception:
        return None


def _int(raw: str | None) -> int | None:
    n = _num(raw)
    return int(n) if n is not None else None


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


async def _have(variant_id: str) -> set[str]:
    async with db.sessionmaker()() as session:
        return {
            sv.attribute
            for sv in (
                await session.execute(
                    select(db.SpecValue).where(db.SpecValue.variant_id == variant_id, db.SpecValue.available)
                )
            ).scalars()
        }


async def missing_critical(variant_id: str, powertrain: str | None = None) -> list[str]:
    have = await _have(variant_id)
    return [k for k in CRITICAL if k not in have] + research_plan.energy_inputs_missing(powertrain, have)


async def last_done(variant_ids: list[str]) -> dict[str, dict[str, Any]]:
    """variant_id -> area -> completed_at (input to the planner's freshness check)."""
    out: dict[str, dict[str, Any]] = defaultdict(dict)
    async with db.sessionmaker()() as s:
        rows = await s.execute(select(db.ResearchRun).where(db.ResearchRun.variant_id.in_(variant_ids)))
        for r in rows.scalars():
            out[r.variant_id][r.area] = r.completed_at
    return out


async def ev_counts(variant_ids: list[str]) -> dict[str, Any]:
    """FR-022 (spec 006): EV values rejected per rule, and weighted plug-in figures kept out of the energy cost."""
    async with db.sessionmaker()() as s:
        rules = await s.execute(
            select(db.Claim.reject_rule, func.count())
            .where(db.Claim.variant_id.in_(variant_ids),
                   db.Claim.reject_rule.like("sense.ev.%") | db.Claim.reject_rule.like("sense.phev.unclear%"))
            .group_by(db.Claim.reject_rule)
        )  # fmt: skip
        wq = select(func.count()).where(db.Claim.variant_id.in_(variant_ids),
                                        db.Claim.attribute == "consumption_weighted")  # fmt: skip
        vq = select(func.count()).where(db.SpecValue.variant_id.in_(variant_ids), db.SpecValue.available.is_(True),
                                        db.SpecValue.attribute == "consumption_weighted")  # fmt: skip
        # a selected weighted value counts once per car even when its claims are gone (seeded or repaired data)
        weighted = max((await s.execute(wq)).scalar() or 0, (await s.execute(vq)).scalar() or 0)
    return {"ev_rejected": {str(r): int(n) for r, n in rules.all()}, "weighted_blocked": int(weighted or 0)}


async def powertrains(variant_ids: list[str]) -> dict[str, str | None]:
    async with db.sessionmaker()() as s:
        rows = await s.execute(select(db.Variant.id, db.Variant.powertrain).where(db.Variant.id.in_(variant_ids)))
        return {vid: pt for vid, pt in rows.all()}


async def registry_done(variant_ids: list[str]) -> dict[str, dict[str, Any]]:
    """variant_id -> area -> when its research last tried the registry's sources with the escalation (spec 010
    FR-022); areas that never did are absent."""
    out: dict[str, dict[str, Any]] = defaultdict(dict)
    async with db.sessionmaker()() as s:
        rows = await s.execute(
            select(db.ResearchRun.variant_id, db.ResearchRun.area, db.ResearchRun.registry_at).where(
                db.ResearchRun.variant_id.in_(variant_ids), db.ResearchRun.registry_at.is_not(None)
            )
        )
        for vid, area, at in rows.all():
            out[str(vid)][str(area)] = at
    return out


async def unmet_areas(variant_ids: list[str]) -> dict[str, set[str]]:
    """variant_id -> areas researched before whose evidence minimum was not reached (worth another try)."""
    out: dict[str, set[str]] = defaultdict(set)
    async with db.sessionmaker()() as s:
        rows = await s.execute(
            select(db.ResearchRun.variant_id, db.ResearchRun.area).where(
                db.ResearchRun.variant_id.in_(variant_ids), db.ResearchRun.minimum_met.is_not(True)
            )
        )
        for vid, area in rows.all():
            out[str(vid)].add(str(area))
        pts = await s.execute(select(db.Variant.id, db.Variant.powertrain).where(db.Variant.id.in_(variant_ids)))
        electrified = [(str(v), pt) for v, pt in pts.all() if (pt or "").upper() in ("BEV", "PHEV", "EREV")]
    for vid, pt in electrified:  # spec 006 FR-009: a run met before the energy rule still lacks the energy inputs
        if research_plan.energy_inputs_missing(pt, await _have(vid)):
            out[vid].add("specs")
    return out


def same_model_generations(ref_generations: dict[str, list[tuple[str, Any, Any]]], v: db.Variant) -> list[str]:
    make, model = identity.normalize_make_model(v.make, v.model)
    return [g for g, _, _ in ref_generations.get(f"{make}|{model}", [])]


async def _interval_from_schedule(session: Any, variant_id: str, selected: dict[str, Any]) -> dict[str, int]:
    """Service interval from the accepted schedule items when no source states it as a single value
    (user report 2026-11-02: the Tucson had a schedule but "no service interval"). European sources only."""
    want = [k for k in ("service_interval_km", "service_interval_months")
            if k not in selected or not selected[k].available]  # fmt: skip
    if not want:
        return {}
    rows = (
        await session.execute(select(db.MaintenanceItem).where(db.MaintenanceItem.variant_id == variant_id))
    ).scalars()
    items = list(rows)
    ev_ids = {i for m in items for i in (m.evidence_ids or [])}
    urls = {}
    if ev_ids:
        urls = {
            e.id: e.url
            for e in (await session.execute(select(db.Evidence).where(db.Evidence.id.in_(ev_ids)))).scalars()
        }
    usable = [
        (m.item, m.interval_km, m.interval_months) for m in items
        if all(sense.market_fits(urls.get(i, ""), "maintenance").ok for i in (m.evidence_ids or []))
    ]  # fmt: skip
    km, months = sense.service_interval_from_items(usable)
    out = {"service_interval_km": km, "service_interval_months": months}
    return {k: v for k, v in out.items() if k in want and v}


async def accepted_gearboxes(variant_id: str) -> list[str]:
    """Gearbox families of the accepted transmission claims of a variant."""
    async with db.sessionmaker()() as s:
        rows = await s.execute(
            select(db.Claim.value_text).where(
                db.Claim.variant_id == variant_id, db.Claim.attribute == "transmission", db.Claim.status == "ACCEPTED"
            )
        )
        return [f for f in (sense.gearbox_family(t) for t in rows.scalars()) if f]


def mixed_families(families: list[str]) -> bool:
    return any(sense.gearbox_conflict(a, b) for i, a in enumerate(families) for b in families[i + 1 :])


async def fill_gearbox(variant_id: str) -> None:
    """Unanimous accepted transmission claims (≥ 2) give the variant its gearbox (spec 004 FR-028)."""
    fams = await accepted_gearboxes(variant_id)
    specific = [f for f in fams if f != "automatic"]
    if len(fams) < 2 or mixed_families(fams):
        return
    fam = specific[0] if specific and len(set(specific)) == 1 else ("automatic" if not specific else None)
    if fam is None:
        return
    async with db.sessionmaker()() as s:
        v = await s.get(db.Variant, variant_id)
        if v is not None and not v.transmission:
            v.transmission = fam
            await s.commit()


def _without_price_outliers(claims: list[Any]) -> list[Any]:
    """A price far from the other sources' prices of the same version is never selected (spec 005 fix)."""
    prices = [(i, float(c.value)) for i, c in enumerate(claims)
              if c.attribute in MONEY_ATTRS and isinstance(c.value, int | float)]  # fmt: skip
    bad = {prices[j][0] for j in sense.price_outliers([v for _, v in prices])}
    return [c for i, c in enumerate(claims) if i not in bad]


async def reselect(variant_id: str) -> None:
    """Recompute selected values for all attributes from all accepted claims (FR-017/FR-018); a variant without
    a gearbox gets it from unanimous transmission claims (spec 004 FR-028)."""
    await fill_gearbox(variant_id)
    async with db.sessionmaker()() as session:
        # parallel jobs for the same car recompute its values one at a time (delete + insert)
        await session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"reselect:{variant_id}"})
        rows = (
            await session.execute(
                select(db.Claim, db.Evidence)
                .join(db.Evidence, db.Claim.evidence_id == db.Evidence.id)
                .where(db.Claim.variant_id == variant_id, db.Claim.status == "ACCEPTED")
            )
        ).all()
        claims = [
            ev.ClaimIn(
                c.id,
                c.attribute,
                c.value_num if c.value_num is not None else (c.value_text or ""),
                e.source_type,
                e.domain,
                c.scope,
            )
            for c, e in rows
        ]
        claims = _without_price_outliers(claims)
        selected = ev.select_all(claims)
        await session.execute(delete(db.SpecValue).where(db.SpecValue.variant_id == variant_id))
        derived = await _interval_from_schedule(session, variant_id, selected)
        for key, sel in selected.items():
            if key in derived:
                continue  # the schedule's interval replaces an empty value
            session.add(
                db.SpecValue(
                    variant_id=variant_id,
                    attribute=key,
                    available=sel.available,
                    value_num=sel.value if isinstance(sel.value, float) else None,
                    value_text=sel.value if isinstance(sel.value, str) else None,
                    provenance=sel.provenance,
                    confidence=sel.confidence,
                    confidence_rule=sel.confidence_rule,
                    resolution_rule=sel.resolution_rule,
                    claim_ids=sel.claim_ids,
                    alternatives=sel.alternatives,
                )
            )
        for key, value in derived.items():
            session.add(
                db.SpecValue(
                    variant_id=variant_id, attribute=key, available=True, value_num=float(value), value_text=None,
                    provenance="SOURCED_FACT", confidence="MEDIUM", confidence_rule="from the service schedule",
                    resolution_rule="schedule", claim_ids=[], alternatives=[],
                )
            )  # fmt: skip
        await session.commit()
