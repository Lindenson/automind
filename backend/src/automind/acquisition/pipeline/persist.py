"""S6 persist (spec 011 strangler, research R5): store what a page gave — its evidence row, the checked spec claims
(the validator role for uncertain pages or values that contradict the stored ones), the reader's table rows, and the
items of the other areas (maintenance, reviews, issues, brand facts, used prices, residual values), each only with a
verbatim excerpt. Moved from `application/research.py` with the bodies unchanged.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select

from automind.acquisition.domain import sense_ev
from automind.acquisition.pipeline import extract as ex
from automind.acquisition.pipeline import stamp
from automind.acquisition.pipeline.locate import favourite_priority
from automind.acquisition.pipeline.plan import is_unverified
from automind.acquisition.pipeline.validate import (
    VALIDATOR_REJECTS,
    ReaderClaim,
    check,
    plausibility_ctx,
    sense_before,
)
from automind.acquisition.ports import AcqPorts
from automind.chat.domain.identification import used
from automind.shared import evidence as ev
from automind.shared.contracts.web import Page, WebDoc
from automind.shared.evidence import sense
from automind.shared.infrastructure import db
from automind.shared.vehicle import specs

VERSION = "persist@1"


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
        unverified=is_unverified(ev.domain_of(d.url)),
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
    ports: AcqPorts,
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
    ports: AcqPorts,
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
    ports: AcqPorts,
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
        from automind.shared.vehicle import units

        return units.parse_number(raw)
    except Exception:
        return None


def _int(raw: str | None) -> int | None:
    n = _num(raw)
    return int(n) if n is not None else None
