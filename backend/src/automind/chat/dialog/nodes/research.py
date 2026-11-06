"""RESEARCH: jobs per car × area, fan-out, gap rounds bounded by depth (R8, R14; FR-019..FR-023).

plan_research (create job rows) → Send(research_job)×N → collect_round → next_round (gaps) ↺ → after_research → assess

Jobs are persisted, so after a restart a job already DONE is not run again (FR-044). One failing job
never fails the turn (FR-023). Areas still below their minimum after the last round are reported as
"insufficient data" (FR-019, constitution XI).
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from langgraph.runtime import Runtime
from langgraph.types import Send

from automind.chat.application.services.research import rounds
from automind.chat.application.services.research.service import ResearchService
from automind.chat.dialog.context import ctx, load_case, record_intake, save_case
from automind.chat.dialog.phrases import t, yes_or_no
from automind.chat.dialog.report_wording import WORDING
from automind.chat.dialog.runner import TurnContext
from automind.chat.dialog.state import RESET, TurnState


def _service(c: TurnContext) -> ResearchService:
    return ResearchService(c.ports, c.budget, c, c.chat_id, c.turn_id)


async def plan_research(state: TurnState, runtime: Runtime[TurnContext]) -> dict[str, Any]:
    c = ctx(runtime)
    keys = set(state["decision"]["cars"])
    plan = [j for j in rounds.plan_of(state.get("research_plan")).jobs if j.car_key in keys]
    await c.status("researching", f"Researching {len(keys)} car(s): {', '.join(sorted({j.area for j in plan}))}")
    _, case = await load_case(c)
    await record_intake(c, "RESEARCH_STARTED", all_confirmed=all(x.resolution in ("CONFIRMED", "AUTO_OK")
                                                                 for x in case.cars if x.key in keys))  # fmt: skip
    return {"jobs": await _service(c).create(case, plan), "round": 0, "research_results": [RESET]}


def fan_out(state: TurnState) -> list[Send] | str:
    sends = [Send("research_job", job) for job in state.get("jobs", [])]
    return sends or "after_research"


async def research_job(job: dict[str, Any], runtime: Runtime[TurnContext]) -> dict[str, Any]:
    c = ctx(runtime)
    _, case = await load_case(c)
    return {"research_results": [await _service(c).run_job(job, case)]}


async def collect_round(state: TurnState, runtime: Runtime[TurnContext]) -> dict[str, Any]:
    c = ctx(runtime)
    results = state.get("research_results", [])
    hit = rounds.limit_hit(results, {j["job_id"] for j in state.get("jobs", [])})
    if hit is not None:  # a limit was reached in this round: ask the user (continue or answer with what exists)
        return {"jobs": [], "limit_hit": hit}
    gaps = rounds.gaps(state.get("research_plan"), results, int(state.get("round", 0)))
    if not gaps:
        return {"jobs": []}
    await c.status("followup", f"Follow-up research for {len(gaps)} area(s) below their minimum")
    _, case = await load_case(c)
    return {"jobs": await _service(c).create(case, gaps), "round": int(state.get("round", 0)) + 1}


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
    if "daily" in hit.get("reasons", []):
        text += t("limit_daily_note", lang, spent=f"{b.day_spent_eur + b.cost_eur:.2f}",
                  cap=f"{b.limits.daily_cap_eur:.2f}")  # fmt: skip
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
        _, case = await load_case(c)
        jobs = await _service(c).create(case, rounds.jobs_of(hit))
        return {"jobs": jobs, "limit_hit": None, "limit_extensions": n, "confirm_payload": None, "resume": None,
                "route": None}  # fmt: skip
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
    _, case = await load_case(c)
    notices, short = _service(c).conclude(case, state.get("research_results", []), list(state.get("notices", [])),
                                          state.get("language"), WORDING)  # fmt: skip
    out: dict[str, Any] = {"research_done": True, "notices": notices, "jobs": []}
    if state.get("request_kind") in ("research_more", "critique") and short:
        for k, a in short:  # "find it" found nothing more: remembered, not offered again for this car and area
            vid = next((x.variant_id for x in case.cars if x.key == k and x.variant_id), None)
            if vid and a not in case.find_tried.get(vid, []):
                case.find_tried.setdefault(vid, []).append(a)
        out["case_version"] = await save_case(
            c, case, [f"searched deeper without the minimum: {', '.join(f'{k} {a}' for k, a in short)}"], publish=False
        )
    return out
