"""Research workers: one job = one car × one area (research R8, R14; FR-013..FR-023).

run_job: area queries (EN + ES) → search with full text → extraction (web reader, no tools) →
programmatic validation (verbatim excerpts, units, ranges) → validator role for pages whose variant
match is uncertain → persist evidence and items → recompute selected values → area freshness and
section minimum. One failing source never fails the job; one failing job never fails the turn.

Constitution I (evidence first), III (code normalizes numbers), VIII (untrusted content), XI (gates).
"""

from __future__ import annotations

import asyncio
import hashlib
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy import delete, func, select, text

from automind.acquisition.pipeline import extract as ex
from automind.acquisition.pipeline import stamp
from automind.acquisition.pipeline.locate import favourite_priority, pages_for
from automind.acquisition.pipeline.parse import _read_tables
from automind.acquisition.pipeline.plan import (
    _plan,
    _variant,
    current_plan,
    known_makes,
)
from automind.acquisition.pipeline.relevance import _llm_per_job, _PageJudge, _relevance_target
from automind.acquisition.pipeline.validate import (
    CRITICAL,
    MONEY_ATTRS,
    VALIDATOR_REJECTS,
    ReaderClaim,
    check,
    known_values,
    plausibility_ctx,
    sense_before,
)
from automind.acquisition.registry.api import Attempt
from automind.application import incentives_research
from automind.application.ports import Page, Ports, WebDoc
from automind.application.usage import BudgetExceeded, current_job
from automind.domain import evidence as ev
from automind.domain import identity, research_plan, search_plan, sense, sense_ev, specs, used
from automind.domain import learned as learned_rules
from automind.domain import relevance as rel
from automind.infrastructure import db

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
    ctx = plausibility_ctx(v, known)
    checked = []
    for c0 in out.claims:
        c, bad = sense_before(c0, v, ev.classify_source(d.url), d.url)
        checked.append((c, *(bad or check(c, d, ctx, ports.ref.plausibility))))
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
    ctx = plausibility_ctx(v, known)
    accepted = rejected = 0
    async with db.sessionmaker()() as s:
        e = await _evidence(s, v, d, page, favourite_priority(ports, v, d.url))
        for row in reading.rows:
            if row.attribute not in specs.ATTRS:
                continue
            c, bad = sense_before(
                ReaderClaim(row.attribute, row.raw_value, row.raw_unit, row.excerpt),
                v,
                ev.classify_source(d.url),
                d.url,
            )
            status, num, txt, rule = bad or check(c, d, ctx, ports.ref.plausibility, excerpt_checked=True)
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
