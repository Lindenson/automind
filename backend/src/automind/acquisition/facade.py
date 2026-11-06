"""The engine side of `acquisition.api` (spec 011 contracts/acquire.md): request → job, job → result.

`acquisition.api` loads this module when the chat calls it, so the chat never imports the engine. One research job
per requested kind; `Need` maps onto today's job flags (research R5, strangler S0).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from automind.acquisition.api import AcquireRequest, AcquireResult, Emit, KindResult, Need, Tried
from automind.acquisition.pipeline import job, merge
from automind.shared.infrastructure import db

TRIED = ("accepted", "rejected", "robots", "junk", "empty", "error")


async def _quiet(stage: str, text: str) -> None:
    return None


def job_spec(req: AcquireRequest, kind: str) -> job.JobSpec:
    """`FRESH` is "find it" (past the cache, wider queries, the other markets); `ESCALATE` an area left short."""
    return job.JobSpec(req.job_id, req.variant_id, kind, req.round, car_year=req.car_year,
                       fresh=req.need is Need.FRESH, escalate=req.need is Need.ESCALATE, market=req.market)  # fmt: skip


async def acquire(req: AcquireRequest, emit: Emit | None, *, ports: Any) -> AcquireResult:
    say = emit or _quiet
    kinds = []
    for kind in req.kinds:
        if req.need is Need.CACHED:
            kinds.append(await cached(req.variant_id, kind))
            continue
        res = await job.run_job(ports, job_spec(req, kind), say)
        kinds.append(KindResult(kind=kind, ok=res.ok, docs=res.docs, accepted=res.accepted, rejected=res.rejected,
                                minimum_met=res.minimum_met, error=res.error, hits=res.hits,
                                tried=await tried(req.job_id, req.variant_id, res.planned),
                                stage_versions=job.STAGE_VERSIONS))  # fmt: skip
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
    hits = await job.area_hits(v, kind)
    if run is None:
        return KindResult(kind=kind, hits=hits)
    return KindResult(kind=kind, docs=run.docs_used, accepted=run.claims_accepted, rejected=run.claims_rejected,
                      minimum_met=bool(run.minimum_met), hits=hits)  # fmt: skip


async def tried(job_id: str, variant_id: str, planned: list[str] | None = None) -> list[Tried]:
    """The sources a job read, one row per domain (its best outcome), from the registry's attempts journal; then the
    `planned` sources (the registry plan's active ones) the job never reached (spec 011 T123, 010 FR-022)."""
    async with db.sessionmaker()() as s:
        rows = (
            await s.execute(
                select(db.RegistryAttempt.url, db.RegistryAttempt.outcome, db.RegistryAttempt.reason)
                .where(db.RegistryAttempt.job_id == job_id, db.RegistryAttempt.variant_id == variant_id)
                .order_by(db.RegistryAttempt.created_at)
            )
        ).all()
    from automind.shared.evidence.evidence import domain_of  # noqa: PLC0415

    out = best_per_domain([(domain_of(url or ""), outcome, reason) for url, outcome, reason in rows])
    reached = {t.domain for t in out}
    for d in planned or []:
        if d not in reached and not any(r.endswith("." + d) for r in reached):
            reached.add(d)
            out.append(Tried(domain=d, outcome="not_reached"))
    return out


def best_per_domain(rows: list[tuple[str, str, str | None]]) -> list[Tried]:
    """(domain, outcome, reason) attempts → one row per domain with its best outcome, in first-attempt order."""
    best: dict[str, Tried] = {}
    for d, outcome, reason in rows:
        out = outcome if outcome in TRIED else "error"
        old = best.get(d)
        if old is None or TRIED.index(out) < TRIED.index(old.outcome):
            best[d] = Tried(domain=d, outcome=out, reason=reason)  # type: ignore[arg-type]
    return list(best.values())


async def tried_by_area(variant_id: str) -> dict[str, list[Tried]]:
    """area → the sources the latest job of that area read for the car, one row per domain (the "no data" item of the
    report names them, spec 011 T123)."""
    async with db.sessionmaker()() as s:
        rows = (
            await s.execute(
                select(db.CapabilityRow.area, db.RegistryAttempt.job_id, db.RegistryAttempt.url,
                       db.RegistryAttempt.outcome, db.RegistryAttempt.reason)
                .join(db.CapabilityRow, db.CapabilityRow.id == db.RegistryAttempt.capability_id)
                .where(db.RegistryAttempt.variant_id == variant_id)
                .order_by(db.RegistryAttempt.created_at)
            )
        ).all()  # fmt: skip
    from automind.shared.evidence.evidence import domain_of  # noqa: PLC0415

    last_job = {str(area): job_id for area, job_id, *_ in rows}  # rows are in time order: the last one wins
    by_area: dict[str, list[tuple[str, str, str | None]]] = {}
    for area, job_id, url, outcome, reason in rows:
        if job_id == last_job[str(area)]:
            by_area.setdefault(str(area), []).append((domain_of(url or ""), str(outcome), reason))
    return {a: best_per_domain(r) for a, r in by_area.items()}


async def gearbox_families_mixed(variant_id: str) -> bool:
    return merge.mixed_families(await merge.accepted_gearboxes(variant_id))


async def reselect(variant_id: str) -> None:
    await merge.reselect(variant_id)
