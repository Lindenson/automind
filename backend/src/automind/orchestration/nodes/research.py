"""RESEARCH: jobs per car × area, fan-out, gap rounds bounded by depth (R8, R14; FR-019..FR-023).

plan_research (create job rows) → Send(research_job)×N → collect_round → next_round (gaps) ↺ → after_research → assess

Jobs are persisted, so after a restart a job already DONE is not run again (FR-044). One failing job
never fails the turn (FR-023). Areas still below their minimum after the last round are reported as
"insufficient data" (FR-019, constitution XI).
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

from langgraph.runtime import Runtime
from langgraph.types import Send

from automind.application import research
from automind.application.research import JobSpec
from automind.application.usage import BudgetExceeded
from automind.domain import research_plan as rp
from automind.orchestration.phrases import t, yes_or_no
from automind.orchestration.report_text import area_label
from automind.orchestration.runner import TurnContext
from automind.orchestration.state import RESET, TurnState

from .common import ctx, load_case, notice, record_intake, save_case


def _plan(state: TurnState) -> rp.ResearchPlan:
    p = state.get("research_plan") or {}
    jobs = [rp.Job(j[0], j[1], j[2], fresh=bool(j[3]) if len(j) > 3 else False) for j in p.get("jobs", [])]
    return rp.ResearchPlan(jobs=jobs, rounds=int(p.get("rounds", 0)))


async def _create(c: TurnContext, jobs: list[rp.Job]) -> list[dict[str, Any]]:
    out = []
    for j in jobs:
        row = await c.ports.jobs.create(c.chat_id, c.turn_id, j.variant_id, j.area, j.round)
        out.append(
            {"job_id": row.id, "car_key": j.car_key, "variant_id": j.variant_id, "area": j.area, "round": j.round,
             "fresh": j.fresh}
        )  # fmt: skip
    _, case = await load_case(c)
    for j in jobs:  # spec 004 FR-023: every cell of the grid appears at once, as queued
        car = next((x for x in case.cars if x.key == j.car_key), None)
        await c.emit("progress", {"car": (car.label or car.request_text) if car else j.car_key, "car_key": j.car_key,
                                  "area": j.area, "state": "queued", "accepted": None, "round": j.round})  # fmt: skip
    return out


async def plan_research(state: TurnState, runtime: Runtime[TurnContext]) -> dict[str, Any]:
    c = ctx(runtime)
    keys = set(state["decision"]["cars"])
    plan = [j for j in _plan(state).jobs if j.car_key in keys]
    areas = sorted({j.area for j in plan})
    await c.status("researching", f"Researching {len(keys)} car(s): {', '.join(areas)}")
    _, case = await load_case(c)
    await record_intake(c, "RESEARCH_STARTED", all_confirmed=all(x.resolution in ("CONFIRMED", "AUTO_OK")
                                                                 for x in case.cars if x.key in keys))  # fmt: skip
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
    if car is None or car.variant_id != job["variant_id"]:  # corrected meanwhile (spec 005): never research the old one
        await c.ports.jobs.mark(job["job_id"], "FAILED", error="superseded by a correction")
        return {"research_results": [{**job, "ok": False, "error": None, "minimum_met": None}]}

    async def progress(state_: str, accepted: int | None = None) -> None:  # spec 004 FR-023: car × area grid
        await c.emit("progress", {"car": label, "car_key": job["car_key"], "area": job["area"], "state": state_,
                                  "accepted": accepted, "round": job.get("round", 0)})  # fmt: skip

    async def emit(stage: str, text: str) -> None:
        await c.status(stage, text, car=label, area=job["area"])
        if stage in ("searching", "researching", "reading", "relevance", "validating"):
            await progress("reading" if stage in ("reading", "relevance", "validating") else "searching")

    pause = c.budget.research_pause()
    if pause is not None:  # near a limit: do not start, ask the user whether to continue (never cancel)
        await progress("paused")
        await c.ports.jobs.mark(job["job_id"], "FAILED", error=f"paused at the {pause} limit")
        return {"research_results": [{**job, "ok": False, "error": f"paused: {pause}", "limit": pause}]}
    await c.ports.jobs.mark(job["job_id"], "RUNNING")
    await progress("searching")
    try:
        async with asyncio.timeout(c.budget.limits.job_timeout_s):
            res = await research.run_job(
                c.ports,
                JobSpec(
                    job["job_id"],
                    job["variant_id"],
                    job["area"],
                    job["round"],
                    car_year=car.year if car else None,
                    fresh=bool(job.get("fresh")),  # "find it": past the search cache, wider queries
                ),
                emit,
            )
    except BudgetExceeded as e:
        await progress("paused")
        await c.ports.jobs.mark(job["job_id"], "FAILED", error=str(e))
        return {"research_results": [{**job, "ok": False, "error": str(e), "limit": e.limit}]}
    except TimeoutError:
        await progress("failed")
        if "job_timeout" not in c.budget.limits_reached:
            c.budget.limits_reached.append("job_timeout")
        await c.ports.jobs.mark(job["job_id"], "FAILED", error="timeout")
        return {"research_results": [{**job, "ok": False, "error": "timeout", "limit": "time"}]}
    status = "DONE" if res.ok else "FAILED"
    await progress("done" if res.ok and res.minimum_met else ("partial" if res.ok and res.accepted else "failed"),
                   res.accepted)  # fmt: skip
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
    current = {j["job_id"] for j in state.get("jobs", [])}
    stopped = [r for r in results if r.get("limit") and r.get("job_id") in current]
    if stopped:  # a limit was reached in this round: ask the user (continue or answer with what exists)
        reasons = sorted({str(r["limit"]) for r in stopped if r["limit"] is not True} or {"calls"})
        todo = [{k: r.get(k) for k in ("car_key", "variant_id", "area", "round", "fresh")} for r in stopped]
        return {"jobs": [], "limit_hit": {"reasons": reasons, "jobs": todo}}
    gaps = rp.gaps(_plan(state), _met(results), round_done=int(state.get("round", 0)))
    if not gaps:
        return {"jobs": []}
    await c.status("followup", f"Follow-up research for {len(gaps)} area(s) below their minimum")
    return {"jobs": await _create(c, gaps), "round": int(state.get("round", 0)) + 1}


def route_round(state: TurnState) -> str:
    if state.get("limit_hit"):
        return "prepare_limit"
    return "next_round" if state.get("jobs") else "after_research"


async def prepare_limit(state: TurnState, runtime: Runtime[TurnContext]) -> dict[str, Any]:
    """Research paused at a limit: offer to continue with one more allowance, or answer now."""
    c = ctx(runtime)
    hit = state.get("limit_hit") or {}
    b = c.budget
    lang = state.get("language")
    reasons = ", ".join(t(f"limit_{r}", lang) for r in hit.get("reasons", []))
    minutes = (time.monotonic() - b.started) / 60
    text = t("limit_reached", lang, reasons=reasons, eur=f"{b.cost_eur:.2f}", calls=b.calls,
             minutes=f"{minutes:.0f}", left=len(hit.get("jobs", [])), more=f"{b.limits.hard_cap_eur:.2f}")  # fmt: skip
    payload = {
        "kind": "limit",
        "action": "CONFIRM_LIMIT",
        "request_id": str(uuid.uuid4()),
        "text": text,
        "options": [
            {"id": "continue", "label": t("limit_continue", lang)},
            {"id": "stop", "label": t("limit_stop", lang)},
        ],
    }
    await c.status("estimating", text)
    return {"confirm_payload": payload}


async def apply_limit(state: TurnState, runtime: Runtime[TurnContext]) -> dict[str, Any]:
    c = ctx(runtime)
    answer = state.get("resume") or {}
    choice = str(answer.get("choice") or "")
    hit = state.get("limit_hit") or {}
    if choice in ("text", "edit", "") and answer.get("text"):
        typed = yes_or_no(answer.get("text"))  # "Continue", "да", "продолжай" … or a new request
        if typed is None:
            c.budget.allow_answer()
            return {"jobs": [], "limit_hit": None, "confirm_payload": None, "resume": None,
                    "user_text": answer.get("text") or "", "route": "interpret"}  # fmt: skip
        choice = "continue" if typed == "yes" else "stop"
    if choice in ("continue", "run", "yes", "confirm"):
        n = int(state.get("limit_extensions") or 0) + 1
        c.budget.extend(n)
        await c.status("researching", f"Continuing: {len(hit.get('jobs', []))} research task(s) left")
        jobs = [rp.Job(j["car_key"], j["variant_id"], j["area"], int(j["round"]), bool(j.get("fresh")))
                for j in hit.get("jobs", [])]  # fmt: skip
        return {"jobs": await _create(c, jobs), "limit_hit": None, "limit_extensions": n, "confirm_payload": None,
                "resume": None, "route": None}  # fmt: skip
    # "stop", a typed reply or anything else: answer with what was collected (nothing is lost)
    c.budget.allow_answer()
    return {"jobs": [], "limit_hit": None, "confirm_payload": None, "resume": None, "route": None}


def route_after_limit(state: TurnState) -> str:
    if state.get("route") == "interpret":
        return "interpret"
    return "next_round" if state.get("jobs") else "after_research"


async def next_round(state: TurnState) -> dict[str, Any]:
    return {}


async def after_research(state: TurnState, runtime: Runtime[TurnContext]) -> dict[str, Any]:
    c = ctx(runtime)
    # research is over: the answer always gets its reserve, even when the jobs used the calls up to the limit
    # (otherwise the report itself hit the limit and the user got "I stopped" instead of the report; flaky
    # test_limit_pause found it)
    c.budget.allow_answer()
    _, case = await load_case(c)
    labels = {x.key: x.label or x.request_text for x in case.cars}
    lang = state.get("language")
    results = state.get("research_results", [])
    notices = list(state.get("notices", []))
    for r in results:
        if not r.get("ok") and r.get("error"):
            notices.append(
                notice(
                    t(
                        "job_incomplete",
                        lang,
                        car=labels.get(r["car_key"], r["car_key"]),
                        area=area_label(r["area"], lang),
                        error=r["error"][:80],
                    ),
                    "warning",
                )
            )
    short = sorted({(k, a) for (k, a), ok in _met(results).items() if not ok})
    for k, a in short:
        notices.append(
            notice(
                t("short_data", lang, car=labels.get(k, k), area=area_label(a, lang)),
                "warning",
                car_key=k,
                area=a,
            )
        )
    seen: set[str] = set()  # a job that timed out before and after "continue" is said once
    notices = [n for n in notices if not (n.get("text") in seen or seen.add(n.get("text")))]  # type: ignore[func-returns-value]
    out: dict[str, Any] = {"research_done": True, "notices": notices, "jobs": []}
    if state.get("request_kind") in ("research_more", "critique") and short:
        for k, a in short:
            vid = next((x.variant_id for x in case.cars if x.key == k and x.variant_id), None)
            if vid and a not in case.find_tried.get(vid, []):
                case.find_tried.setdefault(vid, []).append(a)
        out["case_version"] = await save_case(
            c, case, [f"searched deeper without the minimum: {', '.join(f'{k} {a}' for k, a in short)}"], publish=False
        )
    return out
