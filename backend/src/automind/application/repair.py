"""Data repair after the 2026-11-02 verification fixes (spec 004 FR-027). Idempotent.

1. Spec claims are checked again with the current rules: excerpts are compared without markdown markup (prices
   in bold were rejected), consumption is filed under its test cycle (NEDC figures were taken as WLTP), and a
   manufacturer's WLTP range gives its upper bound (it was rejected as a range).
2. Maintenance items from another market's schedule (e.g. Malaysia) are removed.
3. Selected values are recomputed for every changed car, and area minimums are re-evaluated.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy import delete, or_, select

from automind.application import research as rs
from automind.application.ports import WebDoc
from automind.domain import research_plan, sense
from automind.infrastructure import db

RECHECK = ("ACCEPTED", "REJECTED_UNSUPPORTED", "REJECTED_UNIT")


async def repair_claims(ref: Any) -> dict[str, int]:
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
            if c.attribute not in rs.specs.ATTRS and c.attribute != "consumption":
                continue
            doc = WebDoc(e.url, d.title or "", d.text or "", bool(e.snippet_only))
            claim, bad = rs._sense_before(  # noqa: SLF001 - the same rules as at research time
                rs._ReaderClaim(c.attribute, c.raw_value, c.raw_unit, c.excerpt),
                v,
                e.source_type,  # noqa: SLF001
            )
            if v.id not in known:  # pair checks (battery vs range, usable vs gross) need the car's other values
                known[v.id] = await rs._known_values(v.id)  # noqa: SLF001
            ctx = rs._plausibility_ctx(v, known[v.id])  # noqa: SLF001
            status, num, txt, rule = bad or rs._check(claim, doc, ctx, ref.plausibility)  # noqa: SLF001
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
        q = select(db.MaintenanceItem, db.Variant).join(db.Variant, db.MaintenanceItem.variant_id == db.Variant.id)
        items = (await s.execute(q)).all()
        ev_urls = {x.id: x.url for x in (await s.execute(select(db.Evidence))).scalars()}
        for m, v in items:
            urls = [ev_urls.get(i, "") for i in (m.evidence_ids or [])]
            if any(not sense.market_fits(u, "maintenance").ok for u in urls):
                await s.execute(delete(db.MaintenanceItem).where(db.MaintenanceItem.id == m.id))
                stats["maintenance_other_market_removed"] += 1
                changed.add(v.id)
        await s.commit()
    for vid in changed:
        await rs.reselect(vid)
        await _minimums(vid)
    stats["variants_changed"] = len(changed)
    return dict(stats)


async def _minimums(variant_id: str) -> None:
    async with db.sessionmaker()() as s:
        v = await s.get(db.Variant, variant_id)
        runs = list((await s.execute(select(db.ResearchRun).where(db.ResearchRun.variant_id == variant_id))).scalars())
    if v is None:
        return
    for r in runs:
        if r.area in research_plan.MARKET_AREAS:
            continue  # a market-level area (incentives) has no per-car evidence to count
        try:
            hits = await rs.area_hits(v, r.area)
            met = research_plan.minimum_met(r.area, [research_plan.SourceHit(**h) for h in hits])
        except ValueError:
            continue
        if met != r.minimum_met:
            async with db.sessionmaker()() as s:
                row = await s.get(db.ResearchRun, r.id)
                if row is not None:
                    row.minimum_met = met
                    await s.commit()


async def reclassify_sources() -> dict[str, int]:
    """Source types again with the current rules (reviewer 2026-11-03): fan clubs, dealers and part shops typed
    MANUFACTURER, favourites without their own type. Claims follow with their provenance; selected values and
    area minimums are recomputed for every changed car. Idempotent."""
    from automind.domain import evidence as ev

    stats: Counter[str] = Counter()
    changed: set[str] = set()
    async with db.sessionmaker()() as s:
        moved: dict[str, str] = {}
        for e in (await s.execute(select(db.Evidence))).scalars():
            new = ev.classify_source(e.url)
            if new != e.source_type:
                stats[f"{e.source_type}->{new}"] += 1
                e.source_type = new
                moved[e.id] = new
        if moved:
            claims = (await s.execute(select(db.Claim).where(db.Claim.evidence_id.in_(list(moved))))).scalars()
            for c in claims:
                c.provenance = ev.assign_provenance(moved[c.evidence_id], c.attribute)
                changed.add(c.variant_id)
        await s.commit()
    for vid in changed:
        await rs.reselect(vid)
        await _minimums(vid)
    stats["variants_changed"] = len(changed)
    return dict(stats)
