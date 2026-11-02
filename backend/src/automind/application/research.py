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
from typing import Any

from pydantic import BaseModel
from sqlalchemy import delete, select, text

from automind.application import extraction as ex
from automind.application.ports import Ports, WebDoc
from automind.application.usage import BudgetExceeded, current_job
from automind.domain import evidence as ev
from automind.domain import identity, research_plan, specs
from automind.infrastructure import db

Emit = Callable[[str, str], Awaitable[None]]

CRITICAL = ("max_power", "max_torque", "curb_mass", "drivetrain", "claimed_0_100", "top_speed")
MAX_DOCS_PER_JOB = 5


@dataclass
class JobSpec:
    job_id: str
    variant_id: str
    area: str
    round: int = 0


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


def target_of(v: db.Variant) -> str:
    years = f" ({v.generation_years_from}–{v.generation_years_to or 'now'})" if v.generation_years_from else ""
    return f"{v.label}{years}, powertrain {v.powertrain}, market ES"


def queries_for(ports: Ports, v: db.Variant, area: str, round_: int, missing: list[str]) -> list[str]:
    years = f"{v.generation_years_from}-{v.generation_years_to or ''}" if v.generation_years_from else ""
    fields = {
        "make": v.make,
        "model": v.model,
        "generation": v.generation or "",
        "variant": v.variant_name,
        "years": years,
    }
    out = [" ".join(q.format(**fields).split()) for q in ports.ref.queries.get(area, [])]
    if round_ > 0 and area in ("specs", "engineering") and missing:
        labels = ", ".join(specs.ATTRS[k].label for k in missing if k in specs.ATTRS)
        out.insert(0, f"{v.make} {v.model} {v.generation or ''} {v.variant_name} {labels}")
    return out


async def run_job(ports: Ports, job: JobSpec, emit: Emit) -> JobResult:
    token = current_job.set((job.job_id, job.area))
    try:
        return await _run(ports, job, emit)
    except BudgetExceeded:
        raise
    except Exception as e:  # one failing job never fails the turn (FR-023)
        await emit("researching", f"{job.area}: failed ({type(e).__name__})")
        return JobResult(job.job_id, job.variant_id, job.area, job.round, ok=False, error=f"{type(e).__name__}: {e}")
    finally:
        current_job.reset(token)


async def _run(ports: Ports, job: JobSpec, emit: Emit) -> JobResult:
    v = await _variant(job.variant_id)
    missing = await missing_critical(v.id) if job.area == "specs" else []
    seen = await _used_urls(v.id, job.area)
    docs = await _collect(ports, queries_for(ports, v, job.area, job.round, missing), seen)
    await emit("researching", f"{job.area}: reading {len(docs)} sources" + (" (follow-up)" if job.round else ""))
    target = target_of(v)
    sem = asyncio.Semaphore(4)

    async def one(d: WebDoc) -> tuple[WebDoc, BaseModel | None]:
        async with sem:
            try:
                return d, await ex.extract(ports.llm, ports.ref.prompts, job.area, target, d)
            except BudgetExceeded:
                raise
            except Exception:  # one failing source never fails the job
                return d, None

    extracted = await asyncio.gather(*(one(d) for d in docs))
    await emit("validating", f"{job.area}: validating against the sources")
    others = [g for g, _, _ in ports.ref.generations.get(f"{v.make}|{v.model}", []) if g != v.generation]
    accepted = rejected = 0
    for d, out in extracted:
        if out is None or not getattr(out, "is_about_variant", True):
            continue
        a, r = await _persist(ports, v, job.area, d, out, target, others)
        accepted, rejected = accepted + a, rejected + r
    if job.area in ex.SPEC_AREAS or job.area == "maintenance":
        await reselect(v.id)
    hits = await area_hits(v, job.area)
    met = research_plan.minimum_met(job.area, [research_plan.SourceHit(**h) for h in hits])
    await _mark_run(v.id, job.area, len(docs), accepted, rejected, job.round, met)
    await emit("validating", f"{job.area}: {accepted} accepted, {rejected} rejected by validation")
    return JobResult(
        job.job_id,
        v.id,
        job.area,
        job.round,
        docs=len(docs),
        accepted=accepted,
        rejected=rejected,
        minimum_met=met,
        hits=hits,
    )


async def _variant(variant_id: str) -> db.Variant:
    async with db.sessionmaker()() as s:
        v = await s.get(db.Variant, variant_id)
    if v is None:
        raise ValueError(f"unknown variant {variant_id}")
    return v


async def _collect(ports: Ports, queries: list[str], seen: set[str]) -> list[WebDoc]:
    results = await asyncio.gather(*(ports.search.search(q, max_results=4) for q in queries), return_exceptions=True)
    docs: list[WebDoc] = []
    urls = set(seen)
    for r in results:
        if isinstance(r, BudgetExceeded):
            raise r
        if isinstance(r, BaseException):
            continue
        for d in r:
            if d.url not in urls and not ev.is_denied(d.url):
                urls.add(d.url)
                docs.append(d)
    docs.sort(key=lambda d: (ev.AUTHORITY.index(ev.classify_source(d.url)), d.snippet_only, -len(d.text)))
    docs = docs[:MAX_DOCS_PER_JOB]
    await ports.search.fill_full_text(docs)
    return docs


async def _used_urls(variant_id: str, area: str) -> set[str]:
    async with db.sessionmaker()() as s:
        rows = await s.execute(
            select(db.Evidence.url)
            .join(db.Claim, db.Claim.evidence_id == db.Evidence.id, isouter=True)
            .where(db.Evidence.variant_id == variant_id)
        )
        return {str(u) for u in rows.scalars()}


async def _evidence(s: Any, v: db.Variant, d: WebDoc) -> db.Evidence:
    sha = hashlib.sha256(d.text.encode()).hexdigest()
    doc = (await s.execute(select(db.Document).where(db.Document.content_sha256 == sha))).scalar_one_or_none()
    if doc is None:
        doc = db.Document(url=d.url, title=d.title, text=d.text, content_sha256=sha)
        s.add(doc)
        await s.flush()
    e = db.Evidence(
        variant_id=v.id,
        document_id=doc.id,
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
    ports: Ports, v: db.Variant, area: str, d: WebDoc, out: BaseModel, target: str, others: list[str]
) -> tuple[int, int]:
    uncertain = ev.variant_match_uncertain(
        d.text, d.title, v.generation, others, (v.generation_years_from, v.generation_years_to)
    )
    async with db.sessionmaker()() as s:
        e = await _evidence(s, v, d)
        if area in ex.SPEC_AREAS:
            a, r = await _spec_claims(ports, s, v, area, d, e, out, target, uncertain)
        else:
            a, r = await _items(s, v, area, d, e, out)
        await s.commit()
    return a, r


def _check(c: Any, d: WebDoc) -> tuple[str, float | None, str | None]:
    if specs.RANGE_RE.search(c.raw_value) is None and not ev.validate_excerpt(c.excerpt, c.raw_value, d.text):
        return "REJECTED_UNSUPPORTED", None, None
    try:
        val = specs.normalize(specs.ATTRS[c.attribute], c.raw_value, c.unit)
    except Exception:
        return "REJECTED_UNIT", None, None
    return ("ACCEPTED", val, None) if isinstance(val, float) else ("ACCEPTED", None, str(val))


async def _spec_claims(
    ports: Ports, s: Any, v: db.Variant, area: str, d: WebDoc, e: db.Evidence, out: Any, target: str, uncertain: bool
) -> tuple[int, int]:
    checked = [(c, *_check(c, d)) for c in out.claims]
    verdicts: dict[int, str] = {}
    if uncertain and any(st == "ACCEPTED" for _, st, _, _ in checked):
        verdicts = await ex.validate_claims(
            ports.llm,
            ports.ref.prompts["validator"],
            target,
            d,
            [{"label": c.attribute, "value": c.raw_value, "excerpt": c.excerpt} for c, *_ in checked],
        )
    accepted = rejected = 0
    for i, (c, status, num, txt) in enumerate(checked):
        scope = "GENERATION" if d.snippet_only and c.scope == "VARIANT" else c.scope
        verdict = verdicts.get(i)
        if status == "ACCEPTED" and verdict in ("OTHER_VARIANT", "UNCLEAR"):
            status = f"REJECTED_{verdict}"
        elif status == "ACCEPTED" and verdict == "GENERATION_WIDE":
            scope = "GENERATION"  # kept, but LOW confidence (FR-018)
        accepted += status == "ACCEPTED"
        rejected += status != "ACCEPTED"
        s.add(
            db.Claim(
                variant_id=v.id,
                evidence_id=e.id,
                attribute=c.attribute,
                area=area,
                raw_value=c.raw_value,
                raw_unit=c.unit,
                value_num=num,
                value_text=txt,
                excerpt=c.excerpt,
                scope=scope,
                provenance=ev.assign_provenance(e.source_type, c.attribute),
                status=status,
            )
        )
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
                    interval_km=_int(it.interval_km),
                    interval_months=_int(it.interval_months),
                    cost_eur=_num(it.cost_eur),
                    cost_basis="SOURCED",
                    evidence_ids=[e.id],
                    excerpt=it.excerpt,
                )
            )


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


def _manufacturer(s: Any, v: db.Variant, d: WebDoc, out: Any, k: _Counter) -> None:
    for f in out.facts:
        if k.ok(f.excerpt):
            s.add(
                db.ManufacturerFact(
                    make=v.make,
                    fact_type=f.fact_type,
                    text=f.text,
                    positioning=f.positioning if f.fact_type == "MARKET_POSITION" else None,
                    excerpt=f.excerpt,
                    url=d.url,
                    source_name=d.title[:200],
                )
            )


async def _items(s: Any, v: db.Variant, area: str, d: WebDoc, e: db.Evidence, out: Any) -> tuple[int, int]:
    """Non-numeric areas: keep only items whose excerpt literally occurs in the document."""
    k = _Counter(d.text)
    if area == "maintenance":
        _maintenance(s, v, e, out, k)
    elif area == "reviews":
        _reviews(s, v, e, out, k)
    elif area in ("reliability", "used_issues"):
        _issues(s, v, area, e, out, k)
    elif area == "manufacturer":
        _manufacturer(s, v, d, out, k)
    return k.accepted, k.rejected


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
    table: Any = {"reviews": db.ReviewItem, "reliability": db.Issue, "used_issues": db.Issue}[area]
    q = select(db.Evidence.domain, db.Evidence.source_type).join(table, table.evidence_id == db.Evidence.id)
    q = q.where(table.variant_id == v.id)
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


async def _mark_run(variant_id: str, area: str, docs: int, acc: int, rej: int, round_: int, met: bool) -> None:
    async with db.sessionmaker()() as s:
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


async def missing_critical(variant_id: str) -> list[str]:
    async with db.sessionmaker()() as session:
        have = {
            sv.attribute
            for sv in (
                await session.execute(
                    select(db.SpecValue).where(db.SpecValue.variant_id == variant_id, db.SpecValue.available)
                )
            ).scalars()
        }
    return [k for k in CRITICAL if k not in have]


async def last_done(variant_ids: list[str]) -> dict[str, dict[str, Any]]:
    """variant_id -> area -> completed_at (input to the planner's freshness check)."""
    out: dict[str, dict[str, Any]] = defaultdict(dict)
    async with db.sessionmaker()() as s:
        rows = await s.execute(select(db.ResearchRun).where(db.ResearchRun.variant_id.in_(variant_ids)))
        for r in rows.scalars():
            out[r.variant_id][r.area] = r.completed_at
    return out


def same_model_generations(ref_generations: dict[str, list[tuple[str, Any, Any]]], v: db.Variant) -> list[str]:
    make, model = identity.normalize_make_model(v.make, v.model)
    return [g for g, _, _ in ref_generations.get(f"{make}|{model}", [])]


async def reselect(variant_id: str) -> None:
    """Recompute selected values for all attributes from all accepted claims (FR-017/FR-018)."""
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
        selected = ev.select_all(claims)
        await session.execute(delete(db.SpecValue).where(db.SpecValue.variant_id == variant_id))
        for key, sel in selected.items():
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
        await session.commit()
