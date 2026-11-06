"""Stored claims checked again with the current research-time rules (spec 011 T048; spec 004 FR-022, FR-027).

`recheck_value` serves a user challenge ("this is wrong"), `revalidate_claims` the data repair after rule fixes,
`recheck_minimums` the area minimums after either. The rules are the live ones (`pipeline/validate.py`), never copies.
Moved out of `application/challenge.py` and `application/repair.py`, behaviour unchanged.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy import or_, select

from automind.acquisition.api import Judged, RecheckResult, RevalidateResult
from automind.acquisition.pipeline import job, merge, validate
from automind.shared.contracts.web import WebDoc
from automind.shared.evidence import sense
from automind.shared.infrastructure import db
from automind.shared.research_order import plan as research_plan
from automind.shared.vehicle import specs

# REJECTED_IMPLAUSIBLE: a loosened range (EREV batteries, 2026-11-06) lets a value back
RECHECK = ("ACCEPTED", "REJECTED_UNSUPPORTED", "REJECTED_UNIT", "REJECTED_IMPLAUSIBLE")


async def recheck_value(variant_id: str, attribute: str, *, rules: dict[str, Any] | None = None) -> RecheckResult:
    """The accepted claims behind one value against their documents (excerpt, unit, plausibility, sense, the
    variant's gearbox and drive): failing claims are rejected, then the variant's values are selected again."""
    async with db.sessionmaker()() as s:
        v = await s.get(db.Variant, variant_id)
        if v is None:
            return RecheckResult()
        rows = (
            await s.execute(
                select(db.Claim, db.Evidence, db.Document)
                .join(db.Evidence, db.Claim.evidence_id == db.Evidence.id)
                .join(db.Document, db.Evidence.document_id == db.Document.id)
                .where(
                    db.Claim.variant_id == variant_id, db.Claim.attribute == attribute, db.Claim.status == "ACCEPTED"
                )
            )
        ).all()
        out = RecheckResult(claim_id=rows[0][0].id if rows else None)  # spec 010 FR-006: the claim behind the value
        ctx = validate.plausibility_ctx(v, {})
        for c, e, d in rows:
            claim = validate.ReaderClaim(c.attribute, c.raw_value, c.raw_unit, c.excerpt)
            doc = WebDoc(e.url, d.title or "", d.text or "", bool(e.snippet_only))
            status, _, _, rule = validate.check(claim, doc, ctx, rules)
            if status != "ACCEPTED":
                c.status, c.reject_rule = status, rule or "challenge"
                out.rejected.append({"source": e.domain, "value": c.raw_value, "why": status.lower()})
            else:
                out.kept.append(e.domain)
            excerpt_missing = status == "REJECTED_UNSUPPORTED"  # the quote is not on the page: our extraction erred
            by = "LLM_EXCERPT" if excerpt_missing else c.extracted_by
            out.judged.append(Judged(domain=e.domain, area=c.area or "specs", claim_id=c.id, excerpt=c.excerpt,
                                     by=by, ok=status == "ACCEPTED"))  # fmt: skip
        await s.commit()
    await merge.reselect(variant_id)
    return out


async def revalidate_claims(rules: dict[str, Any] | None) -> RevalidateResult:
    """Spec claims checked again with the current rules (repair after the 2026-11-02 verification fixes)."""
    stats: Counter[str] = Counter()
    changed: set[str] = set()
    known: dict[str, dict[str, float]] = {}
    async with db.sessionmaker()() as s:
        rows = (
            await s.execute(
                select(db.Claim, db.Evidence, db.Document, db.Variant)
                .join(db.Evidence, db.Claim.evidence_id == db.Evidence.id)
                .join(db.Document, db.Evidence.document_id == db.Document.id)
                .join(db.Variant, db.Claim.variant_id == db.Variant.id)
                .where(or_(db.Claim.status.in_(RECHECK), db.Claim.reject_rule.like("sense.%")))
            )
        ).all()
        for c, e, d, v in rows:
            if c.attribute not in specs.ATTRS and c.attribute != "consumption":
                continue
            doc = WebDoc(e.url, d.title or "", d.text or "", bool(e.snippet_only))
            claim, bad = validate.sense_before(
                validate.ReaderClaim(c.attribute, c.raw_value, c.raw_unit, c.excerpt),
                v,
                e.source_type,
                e.url,
            )
            if v.id not in known:  # pair checks (battery vs range, usable vs gross) need the car's other values
                known[v.id] = await validate.known_values(v.id)
            ctx = validate.plausibility_ctx(v, known[v.id])
            status, num, txt, rule = bad or validate.check(claim, doc, ctx, rules)
            wrong_market = not sense.market_fits(e.url, "price").ok
            if status == "ACCEPTED" and claim.attribute == "official_price_es" and wrong_market:
                status, rule = "REJECTED_OTHER_MARKET", "sense.price.other_market"
            if c.status == "ACCEPTED" and status == "REJECTED_UNSUPPORTED":
                continue  # never drop a value accepted earlier only because of a stricter excerpt match
            if (status, claim.attribute, num, txt) != (c.status, c.attribute, c.value_num, c.value_text):
                stats[f"{c.status}->{status}:{claim.attribute}"] += 1
                c.status, c.attribute, c.reject_rule = status, claim.attribute, rule
                c.value_num, c.value_text = num, txt
                changed.add(v.id)
        await s.commit()
    return RevalidateResult(stats=dict(stats), changed=sorted(changed))


async def recheck_minimums(variant_id: str) -> None:
    """The area minimums of a variant's research runs again from its stored evidence."""
    async with db.sessionmaker()() as s:
        v = await s.get(db.Variant, variant_id)
        runs = list((await s.execute(select(db.ResearchRun).where(db.ResearchRun.variant_id == variant_id))).scalars())
    if v is None:
        return
    for r in runs:
        if r.area in research_plan.MARKET_AREAS:
            continue  # a market-level area (incentives) has no per-car evidence to count
        try:
            hits = await job.area_hits(v, r.area)
            met = research_plan.minimum_met(r.area, [research_plan.SourceHit(**h) for h in hits])
        except ValueError:
            continue
        if met != r.minimum_met:
            async with db.sessionmaker()() as s:
                row = await s.get(db.ResearchRun, r.id)
                if row is not None:
                    row.minimum_met = met
                    await s.commit()
