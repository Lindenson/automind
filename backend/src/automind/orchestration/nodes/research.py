"""RESEARCH: jobs per car × area, fan-out, gap rounds bounded by depth (R8, R14; FR-019..FR-023).

plan_research (create job rows) → Send(research_job)×N → collect_round → next_round (gaps) ↺ → after_research → assess

Jobs are persisted, so after a restart a job already DONE is not run again (FR-044). One failing job
never fails the turn (FR-023). Areas still below their minimum after the last round are reported as
"insufficient data" (FR-019, constitution XI).
"""

from __future__ import annotations

import asyncio
from typing import Any

from langgraph.runtime import Runtime
from langgraph.types import Send

from automind.application import research
from automind.application.research import JobSpec
from automind.application.usage import BudgetExceeded
from automind.domain import research_plan as rp
from automind.orchestration.runner import TurnContext
from automind.orchestration.state import RESET, TurnState

from .common import ctx, load_case, notice


def _plan(state: TurnState) -> rp.ResearchPlan:
    p = state.get("research_plan") or {}
    jobs = [rp.Job(k, v, a) for k, v, a in p.get("jobs", [])]
    return rp.ResearchPlan(jobs=jobs, rounds=int(p.get("rounds", 0)))


async def _create(c: TurnContext, jobs: list[rp.Job]) -> list[dict[str, Any]]:
    out = []
    for j in jobs:
        row = await c.ports.jobs.create(c.chat_id, c.turn_id, j.variant_id, j.area, j.round)
        out.append(
            {"job_id": row.id, "car_key": j.car_key, "variant_id": j.variant_id, "area": j.area, "round": j.round}
        )
    return out


async def plan_research(state: TurnState, runtime: Runtime[TurnContext]) -> dict[str, Any]:
    c = ctx(runtime)
    keys = set(state["decision"]["cars"])
    plan = [j for j in _plan(state).jobs if j.car_key in keys]
    areas = sorted({j.area for j in plan})
    await c.status("researching", f"Researching {len(keys)} car(s): {', '.join(areas)}")
    return {"jobs": await _create(c, plan), "round": 0, "research_results": [RESET]}


def fan_out(state: TurnState) -> list[Send] | str:
    sends = [Send("research_job", job) for job in state.get("jobs", [])]
    return sends or "after_research"


async def research_job(job: dict[str, Any], runtime: Runtime[TurnContext]) -> dict[str, Any]:
    c = ctx(runtime)
    row = await c.ports.jobs.get(job["job_id"])  # type: ignore[attr-defined]
    if row is not None and row.status == "DONE":  # resumed after a restart: never redo finished work
        return {"research_results": [{**job, "ok": True, "reused": True, "minimum_met": None}]}
    _, case = await load_case(c)
    car = next((x for x in case.cars if x.key == job["car_key"]), None)
    label = (car.label or car.request_text) if car else job["car_key"]

    async def emit(stage: str, text: str) -> None:
        await c.status(stage, text, car=label, area=job["area"])

    await c.ports.jobs.mark(job["job_id"], "RUNNING")
    try:
        async with asyncio.timeout(c.budget.limits.job_timeout_s):
            res = await research.run_job(
                c.ports,
                JobSpec(
                    job["job_id"], job["variant_id"], job["area"], job["round"], car_year=car.year if car else None
                ),
                emit,
            )
    except BudgetExceeded as e:
        await c.ports.jobs.mark(job["job_id"], "FAILED", error=str(e))
        return {"research_results": [{**job, "ok": False, "error": str(e), "limit": True}]}
    except TimeoutError:
        if "job_timeout" not in c.budget.limits_reached:
            c.budget.limits_reached.append("job_timeout")
        await c.ports.jobs.mark(job["job_id"], "FAILED", error="timeout")
        return {"research_results": [{**job, "ok": False, "error": "timeout"}]}
    status = "DONE" if res.ok else "FAILED"
    await c.ports.jobs.mark(
        job["job_id"], status, docs=res.docs, accepted=res.accepted, rejected=res.rejected, error=res.error
    )
    return {
        "research_results": [
            {
                **job,
                "ok": res.ok,
                "minimum_met": res.minimum_met,
                "error": res.error,
                "accepted": res.accepted,
                "rejected": res.rejected,
            }
        ]
    }


def _met(results: list[dict[str, Any]]) -> dict[tuple[str, str], bool]:
    met: dict[tuple[str, str], bool] = {}
    for r in results:  # later rounds override earlier ones
        if r.get("minimum_met") is not None:
            met[(r["car_key"], r["area"])] = bool(r["minimum_met"])
        elif r.get("reused"):
            met.setdefault((r["car_key"], r["area"]), True)
    return met


async def collect_round(state: TurnState, runtime: Runtime[TurnContext]) -> dict[str, Any]:
    c = ctx(runtime)
    results = state.get("research_results", [])
    if any(r.get("limit") for r in results):
        return {"jobs": []}  # a limit was reached: stop researching, answer with what we have
    gaps = rp.gaps(_plan(state), _met(results), round_done=int(state.get("round", 0)))
    if not gaps:
        return {"jobs": []}
    await c.status("followup", f"Follow-up research for {len(gaps)} area(s) below their minimum")
    return {"jobs": await _create(c, gaps), "round": int(state.get("round", 0)) + 1}


def route_round(state: TurnState) -> str:
    return "next_round" if state.get("jobs") else "after_research"


async def next_round(state: TurnState) -> dict[str, Any]:
    return {}


async def after_research(state: TurnState, runtime: Runtime[TurnContext]) -> dict[str, Any]:
    c = ctx(runtime)
    _, case = await load_case(c)
    labels = {x.key: x.label or x.request_text for x in case.cars}
    results = state.get("research_results", [])
    notices = list(state.get("notices", []))
    for r in results:
        if not r.get("ok") and r.get("error"):
            notices.append(
                notice(
                    f"{labels.get(r['car_key'], r['car_key'])}: {r['area']} research incomplete ({r['error'][:80]})",
                    "warning",
                )
            )
    short = sorted({(k, a) for (k, a), ok in _met(results).items() if not ok})
    for k, a in short:
        notices.append(
            notice(
                f"{labels.get(k, k)}: insufficient data for {a.replace('_', ' ')} (minimum evidence not reached)",
                "warning",
            )
        )
    return {"research_done": True, "notices": notices, "jobs": []}
