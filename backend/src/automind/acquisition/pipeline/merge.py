"""S6 merge (spec 011 strangler, research R5): the selected value of every attribute of a variant from all its
accepted claims (evidence rules, price outliers left out, the service interval from the schedule), and the
variant's gearbox from unanimous transmission claims. Moved from `application/research.py` with the bodies unchanged.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select, text

from automind.acquisition.pipeline.validate import MONEY_ATTRS
from automind.domain import evidence as ev
from automind.domain import sense
from automind.infrastructure import db

VERSION = "merge@1"


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
