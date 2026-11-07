"""Research rounds (R8, R14; FR-019..FR-023): the jobs of a plan as carried in the turn state, what the engine is
asked for each job, which car × area reached its minimum, and what the round leaves — a limit to ask about, the
gaps for another round, or nothing. Pure functions over the state shapes of `contracts.py`."""

from __future__ import annotations

from collections.abc import Sequence

from automind.acquisition import api as acquisition
from automind.chat.application.services.research.contracts import (
    JobResult,
    JobState,
    LimitHit,
    PlanRow,
    PlanState,
    StoppedJob,
)
from automind.shared.research_order import plan as rp

DEFAULT_LIMIT = "calls"  # a stop recorded as `True` (checkpoints written before the reasons were named)


def plan_of(state_plan: PlanState | None) -> rp.ResearchPlan:
    """The research plan the turn state carries (empty when there is none)."""
    p = state_plan or {}
    return rp.ResearchPlan(jobs=[_job_of(row) for row in p.get("jobs", [])], rounds=int(p.get("rounds", 0)))


def need_of(job: JobState) -> acquisition.Need:
    """What the engine is asked for: "find it" (fresh: past the search cache, wider queries); an area left short
    before (escalate: the registry's other markets too); a gap round; or a first round."""
    if job.get("fresh"):
        return acquisition.Need.FRESH
    if job.get("escalate"):
        return acquisition.Need.ESCALATE
    return acquisition.Need.FOLLOW_UP if job.get("round") else acquisition.Need.STANDARD


def minimum_met(results: Sequence[JobResult]) -> dict[tuple[str, str], bool]:
    """(car key, area) -> whether the minimum was reached; a later round overrides an earlier one, a reused job
    counts as met unless a round says otherwise."""
    met: dict[tuple[str, str], bool] = {}
    for r in results:
        known = r.get("minimum_met")
        if known is not None:
            met[(r["car_key"], r["area"])] = bool(known)
        elif r.get("reused"):
            met.setdefault((r["car_key"], r["area"]), True)
    return met


def limit_hit(results: Sequence[JobResult], current: set[str]) -> LimitHit | None:
    """A limit reached by a job of this round (`current`: its job ids): the reasons and the jobs to run if the
    person goes on; None when the round ran through."""
    stopped = [r for r in results if r.get("limit") and r["job_id"] in current]
    if not stopped:
        return None
    reasons = sorted({r["limit"] for r in stopped if not isinstance(r["limit"], bool)} or {DEFAULT_LIMIT})
    return {"reasons": reasons, "jobs": [_stopped(r) for r in stopped]}


def gaps(state_plan: PlanState | None, results: Sequence[JobResult], round_done: int) -> list[rp.Job]:
    """The jobs of another round for the areas still below their minimum (bounded by the plan's rounds)."""
    return rp.gaps(plan_of(state_plan), minimum_met(results), round_done=round_done)


def jobs_of(hit: LimitHit) -> list[rp.Job]:
    """The jobs a limit stopped, to run again."""
    return [rp.Job(j["car_key"], j["variant_id"], j["area"], int(j["round"]), bool(j.get("fresh")),
                   bool(j.get("escalate"))) for j in hit["jobs"]]  # fmt: skip


def _job_of(row: PlanRow) -> rp.Job:
    car_key, variant_id, area = (str(x) for x in row[:3])
    return rp.Job(car_key, variant_id, area, fresh=len(row) > 3 and bool(row[3]),
                  escalate=len(row) > 4 and bool(row[4]))  # fmt: skip


def _stopped(r: JobResult) -> StoppedJob:
    # `.get`: a job in a checkpoint written before 2026-11 may lack the flags (read as "not set")
    return {"car_key": r["car_key"], "variant_id": r["variant_id"], "area": r["area"], "round": r["round"],
            "fresh": r.get("fresh", False), "escalate": r.get("escalate", False)}  # fmt: skip
