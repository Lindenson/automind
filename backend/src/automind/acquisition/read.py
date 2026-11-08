"""The engine's read model (spec 011 contracts/acquire.md): what is stored per car — missing critical values, area
freshness, EV rejections, powertrains, registry escalations, areas below their minimum. No network or model call.
Moved from `application/research.py` with the bodies unchanged.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import func, select

from automind.acquisition.pipeline import plan
from automind.acquisition.pipeline.domain import critical
from automind.shared.infrastructure import db
from automind.shared.research_order import plan as research_plan


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
    return critical.missing_critical(await _have(variant_id), powertrain)


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
    FR-022); areas that never did are absent. A run planned by an older planner counts as not tried: its markets
    and queries were other ones (chat 2026-11-06: a run before the home-market research blocked the Chinese search
    of an unmet area for the retry window), so the unmet area is tried again at once."""
    out: dict[str, dict[str, Any]] = defaultdict(dict)
    async with db.sessionmaker()() as s:
        r = db.ResearchRun
        rows = await s.execute(
            select(r.variant_id, r.area, r.registry_at, r.stage_versions).where(
                r.variant_id.in_(variant_ids), r.registry_at.is_not(None)
            )
        )
        for vid, area, at, versions in rows.all():
            if (versions or {}).get("plan", plan.VERSION) == plan.VERSION:
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
