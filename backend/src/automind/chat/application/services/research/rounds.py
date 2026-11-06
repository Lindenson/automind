"""Research rounds (R8, R14; FR-019..FR-023): the jobs of a plan as carried in the turn state, what the engine is
asked for each job, which car × area reached its minimum, and what the round leaves — a limit to ask about, the
gaps for another round, or nothing."""

from __future__ import annotations

from typing import Any

from automind.acquisition import api as acquisition
from automind.shared.research_order import plan as rp

JOB_KEYS = ("car_key", "variant_id", "area", "round", "fresh", "escalate")  # a job to run again after a limit


def plan_of(state_plan: dict[str, Any] | None) -> rp.ResearchPlan:
    """The research plan as the turn state carries it (jobs as lists)."""
    p = state_plan or {}
    jobs = [rp.Job(j[0], j[1], j[2], fresh=bool(j[3]) if len(j) > 3 else False,
                   escalate=bool(j[4]) if len(j) > 4 else False) for j in p.get("jobs", [])]  # fmt: skip
    return rp.ResearchPlan(jobs=jobs, rounds=int(p.get("rounds", 0)))


def need_of(job: dict[str, Any]) -> acquisition.Need:
    """ "Find it" (fresh: past the search cache, wider queries); an area left short before (escalate: the
    registry's other markets too); a gap round; or a first round."""
    if job.get("fresh"):
        return acquisition.Need.FRESH
    if job.get("escalate"):
        return acquisition.Need.ESCALATE
    return acquisition.Need.FOLLOW_UP if job.get("round") else acquisition.Need.STANDARD


def minimum_met(results: list[dict[str, Any]]) -> dict[tuple[str, str], bool]:
    """(car key, area) -> whether the minimum was reached; later rounds override earlier ones."""
    met: dict[tuple[str, str], bool] = {}
    for r in results:
        if r.get("minimum_met") is not None:
            met[(r["car_key"], r["area"])] = bool(r["minimum_met"])
        elif r.get("reused"):
            met.setdefault((r["car_key"], r["area"]), True)
    return met


def limit_hit(results: list[dict[str, Any]], current: set[str]) -> dict[str, Any] | None:
    """A limit reached in this round: its reasons and the jobs to run if the person goes on; else None."""
    stopped = [r for r in results if r.get("limit") and r.get("job_id") in current]
    if not stopped:
        return None
    reasons = sorted({str(r["limit"]) for r in stopped if r["limit"] is not True} or {"calls"})
    return {"reasons": reasons, "jobs": [{k: r.get(k) for k in JOB_KEYS} for r in stopped]}


def gaps(state_plan: dict[str, Any] | None, results: list[dict[str, Any]], round_done: int) -> list[rp.Job]:
    """The jobs of another round for the areas still below their minimum (bounded by the plan's rounds)."""
    return rp.gaps(plan_of(state_plan), minimum_met(results), round_done=round_done)


def jobs_of(hit: dict[str, Any]) -> list[rp.Job]:
    """The jobs a limit stopped, to run again."""
    return [rp.Job(j["car_key"], j["variant_id"], j["area"], int(j["round"]), bool(j.get("fresh")),
                   bool(j.get("escalate"))) for j in hit.get("jobs", [])]  # fmt: skip
