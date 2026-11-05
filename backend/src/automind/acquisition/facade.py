"""The engine side of `acquisition.api` (spec 011 contracts/acquire.md): request → job, job → result.

`acquisition.api` loads this module when the chat calls it, so the chat never imports the engine. One research job
per requested kind; `Need` maps onto today's job flags (research R5, strangler S0).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from automind.acquisition.api import AcquireRequest, AcquireResult, Emit, KindResult, Need, Tried
from automind.acquisition.pipeline import merge
from automind.application import research
from automind.infrastructure import db

TRIED = ("accepted", "rejected", "robots", "junk", "empty", "error")


async def _quiet(stage: str, text: str) -> None:
    return None


def job_spec(req: AcquireRequest, kind: str) -> research.JobSpec:
    """`FRESH` is "find it" (past the cache, wider queries, the other markets); `ESCALATE` an area left short."""
    return research.JobSpec(req.job_id, req.variant_id, kind, req.round, car_year=req.car_year,
                            fresh=req.need is Need.FRESH, escalate=req.need is Need.ESCALATE)  # fmt: skip


async def acquire(req: AcquireRequest, emit: Emit | None, *, ports: Any) -> AcquireResult:
    if ports is None:
        raise TypeError("acquire() needs the engine's ports")
    say = emit or _quiet
    kinds = []
    for kind in req.kinds:
        if req.need is Need.CACHED:
            kinds.append(await cached(req.variant_id, kind))
            continue
        res = await research.run_job(ports, job_spec(req, kind), say)
        kinds.append(KindResult(kind=kind, ok=res.ok, docs=res.docs, accepted=res.accepted, rejected=res.rejected,
                                minimum_met=res.minimum_met, error=res.error, hits=res.hits,
                                tried=await tried(req.job_id, req.variant_id)))  # fmt: skip
    return AcquireResult(job_id=req.job_id, variant_id=req.variant_id, round=req.round, kinds=kinds)


async def cached(variant_id: str, kind: str) -> KindResult:
    """What the engine already holds for a kind: no search, fetch or model call."""
    async with db.sessionmaker()() as s:
        v = await s.get(db.Variant, variant_id)
        run = (
            await s.execute(
                select(db.ResearchRun).where(db.ResearchRun.variant_id == variant_id, db.ResearchRun.area == kind)
            )
        ).scalar_one_or_none()
    if v is None:
        return KindResult(kind=kind, ok=False, error=f"unknown variant {variant_id}")
    hits = await research.area_hits(v, kind)
    if run is None:
        return KindResult(kind=kind, hits=hits)
    return KindResult(kind=kind, docs=run.docs_used, accepted=run.claims_accepted, rejected=run.claims_rejected,
                      minimum_met=bool(run.minimum_met), hits=hits)  # fmt: skip


async def tried(job_id: str, variant_id: str) -> list[Tried]:
    """The sources a job read, one row per domain (its best outcome), from the registry's attempts journal."""
    async with db.sessionmaker()() as s:
        rows = (
            await s.execute(
                select(db.RegistryAttempt.url, db.RegistryAttempt.outcome, db.RegistryAttempt.reason)
                .where(db.RegistryAttempt.job_id == job_id, db.RegistryAttempt.variant_id == variant_id)
                .order_by(db.RegistryAttempt.created_at)
            )
        ).all()
    from automind.domain.evidence import domain_of  # noqa: PLC0415

    best: dict[str, Tried] = {}
    for url, outcome, reason in rows:
        out = outcome if outcome in TRIED else "error"
        d = domain_of(url or "")
        old = best.get(d)
        if old is None or TRIED.index(out) < TRIED.index(old.outcome):
            best[d] = Tried(domain=d, outcome=out, reason=reason)
    return list(best.values())


async def missing_critical(variant_id: str, powertrain: str | None = None) -> list[str]:
    return await research.missing_critical(variant_id, powertrain)


async def last_done(variant_ids: list[str]) -> dict[str, dict[str, Any]]:
    return await research.last_done(variant_ids)


async def ev_counts(variant_ids: list[str]) -> dict[str, Any]:
    return await research.ev_counts(variant_ids)


async def powertrains(variant_ids: list[str]) -> dict[str, str | None]:
    return await research.powertrains(variant_ids)


async def registry_done(variant_ids: list[str]) -> dict[str, dict[str, Any]]:
    return await research.registry_done(variant_ids)


async def unmet_areas(variant_ids: list[str]) -> dict[str, set[str]]:
    return await research.unmet_areas(variant_ids)


async def gearbox_families_mixed(variant_id: str) -> bool:
    return merge.mixed_families(await merge.accepted_gearboxes(variant_id))


async def reselect(variant_id: str) -> None:
    await merge.reselect(variant_id)
