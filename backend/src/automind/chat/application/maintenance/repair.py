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

from sqlalchemy import delete, select

from automind.acquisition import api as acquisition
from automind.shared.evidence import sense
from automind.shared.infrastructure import db


async def repair_claims(ref: Any) -> dict[str, int]:
    checked = await acquisition.revalidate_claims(ref.plausibility)
    stats: Counter[str] = Counter(checked.stats)
    changed: set[str] = set(checked.changed)
    async with db.sessionmaker()() as s:
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
        await acquisition.reselect(vid)
        await acquisition.recheck_minimums(vid)
    stats["variants_changed"] = len(changed)
    return dict(stats)


async def reclassify_sources() -> dict[str, int]:
    """Source types again with the current rules (reviewer 2026-11-03): fan clubs, dealers and part shops typed
    MANUFACTURER, favourites without their own type. Claims follow with their provenance; selected values and
    area minimums are recomputed for every changed car. Idempotent."""
    from automind.shared.evidence import evidence as ev

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
        await acquisition.reselect(vid)
        await acquisition.recheck_minimums(vid)
    stats["variants_changed"] = len(changed)
    return dict(stats)


# --- catalog clean-up: one row per car (duplicates named differently by the resolver) --------------------------

_FILL = ("generation", "generation_years_from", "generation_years_to", "model_year_from", "body_class",
         "vehicle_class", "segment", "brand_positioning", "transmission", "drive", "trim", "trim_level", "price_eur",
         "engine_cc", "power_kw", "fuel")  # fmt: skip
_UNIQUE = {"spec_values": "attribute", "research_runs": "area"}  # (variant_id, column) is unique there


_FK = ("claims", "evidence", "feasibility_checks", "issues", "maintenance_items", "page_relevance",
       "reliability_stats", "research_jobs", "research_runs", "review_items", "spec_values", "tco_estimates",
       "used_price_ranges", "value_retention", "value_challenges")  # fmt: skip


async def merge_duplicates(apply: bool = False, make: str | None = None) -> dict[str, Any]:
    """Fold catalog rows that are one car (identity.same_version) into the row with the most evidence: research,
    chats and saved conversations then point at that row, and its selected values are computed from all claims.
    Without apply nothing is written (the plan is computed in a transaction that is rolled back)."""
    from sqlalchemy import text

    moved: Counter[str] = Counter()
    async with db.sessionmaker()() as s:
        await _canonical_makes(s, moved)  # "Škoda" and "Skoda" are one make before rows are compared
        await (s.commit() if apply else s.rollback())
    plan = await _merge_plan(make)
    async with db.sessionmaker()() as s:
        json_cols = (await s.execute(text(
            "select table_name, column_name, data_type from information_schema.columns "
            "where table_schema = current_schema() and data_type in ('json', 'jsonb')"))).all()  # fmt: skip
        for p in plan:
            await _fold(s, p["keep"], p["fold"], moved)
        swap = {old: p["keep"] for p in plan for old in p["fold"]}
        if swap:
            await _repoint_stored_ids(s, swap, [(str(t), str(c), str(typ)) for t, c, typ in json_cols], moved)
        await (s.commit() if apply else s.rollback())
    if apply:
        for p in plan:
            await acquisition.reselect(p["keep"])
            await acquisition.recheck_minimums(p["keep"])
    return {"applied": apply, "groups": plan, "rows": dict(moved)}


async def _canonical_makes(s: Any, moved: Counter[str]) -> None:
    from automind.shared.infrastructure.config.loader import load_yaml
    from automind.shared.vehicle.makes import MakeRegistry

    reg = MakeRegistry.from_config(load_yaml("makes.yaml"))
    for v in (await s.execute(select(db.Variant))).scalars():
        canon = reg.canonical(v.make)
        if canon and canon != v.make:
            v.make = canon
            moved["make_spelling"] += 1


async def _merge_plan(make: str | None) -> list[dict[str, Any]]:
    """Groups of one car; the row with the most accepted claims (then the most known fields, then the oldest) stays."""
    from automind.chat.application.services.identification.resolve import variant_dict
    from automind.shared.vehicle import identity

    async with db.sessionmaker()() as s:
        q = select(db.Variant) if make is None else select(db.Variant).where(db.Variant.make == make)
        variants = list((await s.execute(q)).scalars())
        claims = Counter(
            r[0] for r in (await s.execute(select(db.Claim.variant_id).where(db.Claim.status == "ACCEPTED"))).all()
        )
    by_id = {v.id: v for v in variants}
    plan: list[dict[str, Any]] = []
    for group in identity.duplicate_groups([{**variant_dict(v), "id": v.id} for v in variants]):
        ranked = sorted(group, key=lambda i: (-claims[i], -sum(getattr(by_id[i], c) is not None for c in _FILL),
                                              by_id[i].created_at))  # fmt: skip
        plan.append({"keep": ranked[0], "fold": ranked[1:], "labels": {i: by_id[i].label for i in ranked},
                     "accepted_claims": {i: claims[i] for i in ranked}})  # fmt: skip
    return plan


async def _fold(s: Any, keep: str, fold: list[str], moved: Counter[str]) -> None:
    """Research rows move to the kept car (its own selected value / freshness wins), then the folded rows go."""
    from sqlalchemy import text

    k = await s.get(db.Variant, keep)
    for old in fold:
        o = await s.get(db.Variant, old)
        for c in _FILL:  # what only the folded row knew
            if getattr(k, c) is None and getattr(o, c) is not None:
                setattr(k, c, getattr(o, c))
        for t in _FK:
            if t in _UNIQUE:
                col = _UNIQUE[t]
                r = await s.execute(text(
                    f"delete from {t} where variant_id = :o and {col} in "
                    f"(select {col} from {t} where variant_id = :k)"), {"o": old, "k": keep})  # fmt: skip
                moved[f"{t}_dropped"] += r.rowcount or 0
            r = await s.execute(text(f"update {t} set variant_id = :k where variant_id = :o"), {"o": old, "k": keep})
            moved[t] += r.rowcount or 0
        await s.flush()
        await s.delete(o)
        moved["variants_removed"] += 1
    if k.trim and k.trim.strip().lower() == k.model.strip().lower():  # "Terramar" is the model, not a version
        k.trim = None
        if k.variant_name.lower().endswith(" " + k.model.lower()):
            k.variant_name = k.variant_name[: -len(k.model) - 1]
        moved["model_as_version_cleared"] += 1


async def _repoint_stored_ids(s: Any, swap: dict[str, str], json_cols: list[tuple[str, str, str]],
                              moved: Counter[str]) -> None:  # fmt: skip
    """Case files, messages, events, simulations and the saved conversation state keep variant ids as data: one
    pass per column for all folded ids (each column is scanned once)."""
    from sqlalchemy import text

    olds = list(swap)
    params: dict[str, Any] = {f"o{i}": o for i, o in enumerate(olds)} | {f"k{i}": swap[o] for i, o in enumerate(olds)}
    pats = {"pats": [f"%{o}%" for o in olds]}
    for t, c, typ in json_cols:
        expr = f'"{c}"::text'
        for i in range(len(olds)):
            expr = f"replace({expr}, :o{i}, :k{i})"
        r = await s.execute(text(f'update "{t}" set "{c}" = {expr}::{typ} where "{c}"::text like any(:pats)'),
                            params | pats)  # fmt: skip
        moved[f"{t}.{c}"] += r.rowcount or 0
    needles = " or ".join(f"position(:b{i} in blob) > 0" for i in range(len(olds)))
    bparams = {f"b{i}": o.encode() for i, o in enumerate(olds)}
    for t in ("checkpoint_blobs", "checkpoint_writes"):  # msgpack: the same-length id swaps in place
        found = (await s.execute(text(f"select ctid::text, blob from {t} where {needles}"), bparams)).all()
        for ctid, blob in found:
            new = bytes(blob)
            for o, k in swap.items():
                new = new.replace(o.encode(), k.encode())
            await s.execute(text(f"update {t} set blob = :b where ctid::text = :c"), {"b": new, "c": ctid})
        moved[t] += len(found)
