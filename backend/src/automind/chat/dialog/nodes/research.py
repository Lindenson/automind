"""RESEARCH: jobs per car × area, fan-out, gap rounds bounded by depth (R8, R14; FR-019..FR-023).

plan_research (create job rows) → Send(research_job)×N → collect_round → next_round (gaps) ↺ → after_research → assess

Jobs are persisted, so after a restart a job already DONE is not run again (FR-044). One failing job
never fails the turn (FR-023). Areas still below their minimum after the last round are reported as
"insufficient data" (FR-019, constitution XI).
"""

from __future__ import annotations

import time
import uuid

from langgraph.types import Send

from automind.chat.application.services.research import rounds
from automind.chat.application.services.research.contracts import LimitHit
from automind.chat.application.services.research.service import ResearchService
from automind.chat.dialog.context import record_intake
from automind.chat.dialog.contract import node
from automind.chat.dialog.nodes.confirm_io import ConfirmOut
from automind.chat.dialog.nodes.research_io import (
    AfterResearchIn,
    AfterResearchOut,
    ApplyLimitIn,
    ApplyLimitOut,
    CollectRoundIn,
    CollectRoundOut,
    LimitIn,
    NothingIn,
    NothingOut,
    PlanResearchIn,
    PlanResearchOut,
    ResearchJobIn,
    ResearchJobOut,
)
from automind.chat.dialog.phrases import t, yes_or_no
from automind.chat.dialog.report_wording import WORDING
from automind.chat.dialog.state import RESET, TurnState
from automind.chat.dialog.turn.context import TurnContext


@node("plan_research", reads=PlanResearchIn, writes=PlanResearchOut)
async def plan_research(inp: PlanResearchIn, c: TurnContext) -> PlanResearchOut:
    """The research jobs of the plan for the cars the policy chose, created as rows (a restart never reruns one)."""
    keys = set(inp.decision["cars"])
    plan = [j for j in rounds.plan_of(inp.research_plan).jobs if j.car_key in keys]
    await c.status("researching", f"Researching {len(keys)} car(s): {', '.join(sorted({j.area for j in plan}))}")
    case = await c.case()
    await record_intake(c, "RESEARCH_STARTED", all_confirmed=all(x.resolution in ("CONFIRMED", "AUTO_OK")
                                                                 for x in case.cars if x.key in keys))  # fmt: skip
    return PlanResearchOut(jobs=await _service(c).create(case, plan), round=0, research_results=[RESET])


def fan_out(state: TurnState) -> list[Send] | str:
    sends = [Send("research_job", job) for job in state.get("jobs", [])]
    return sends or "after_research"


@node("research_job", reads=ResearchJobIn, writes=ResearchJobOut, sent=True)
async def research_job(inp: ResearchJobIn, c: TurnContext) -> ResearchJobOut:
    """One job (car × area) run by a parallel worker; its result is appended to the round's results."""
    case = await c.case()
    return ResearchJobOut(research_results=[await _service(c).run_job(inp.job(), case)])


@node("collect_round", reads=CollectRoundIn, writes=CollectRoundOut)
async def collect_round(inp: CollectRoundIn, c: TurnContext) -> CollectRoundOut:
    """The round's results: a limit pauses the research; areas below their minimum get a follow-up round."""
    results = inp.research_results
    hit = rounds.limit_hit(results, {j["job_id"] for j in inp.jobs})
    if hit is not None:  # a limit was reached in this round: ask the user (continue or answer with what exists)
        return CollectRoundOut(jobs=[], limit_hit=hit)
    gaps = rounds.gaps(inp.research_plan, results, int(inp.round))
    if not gaps:
        return CollectRoundOut(jobs=[])
    await c.status("followup", f"Follow-up research for {len(gaps)} area(s) below their minimum")
    case = await c.case()
    return CollectRoundOut(jobs=await _service(c).create(case, gaps), round=int(inp.round) + 1)


def route_round(state: TurnState) -> str:
    if state.get("limit_hit"):
        return "prepare_limit"
    return "next_round" if state.get("jobs") else "after_research"


@node("prepare_limit", reads=LimitIn, writes=ConfirmOut)
async def prepare_limit(inp: LimitIn, c: TurnContext) -> ConfirmOut:
    """Research paused at a limit: offer to continue with one more allowance, or answer now."""
    hit = inp.limit_hit or LimitHit(reasons=[], jobs=[])
    b = c.budget
    lang = inp.language
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
    return ConfirmOut(confirm_payload=payload)


@node("apply_limit", reads=ApplyLimitIn, writes=ApplyLimitOut)
async def apply_limit(inp: ApplyLimitIn, c: TurnContext) -> ApplyLimitOut:
    """The limit answer: continue with one more allowance, stop and answer with what was collected, or (typed words
    that are not a yes/no) stop and read them as a new message."""
    answer = inp.resume or {}
    choice = str(answer.get("choice") or "")
    hit = inp.limit_hit or LimitHit(reasons=[], jobs=[])
    if choice in ("text", "edit", "") and answer.get("text"):
        typed = yes_or_no(answer.get("text"))  # "Continue", "да", "продолжай" … or a new request
        if typed is None:
            c.budget.allow_answer()
            return ApplyLimitOut(jobs=[], limit_hit=None, confirm_payload=None, resume=None,
                                 user_text=answer.get("text") or "", route="interpret")  # fmt: skip
        choice = "continue" if typed == "yes" else "stop"
    if choice in ("continue", "run", "yes", "confirm"):
        n = int(inp.limit_extensions or 0) + 1
        c.budget.extend(n)
        await c.status("researching", f"Continuing: {len(hit.get('jobs', []))} research task(s) left")
        case = await c.case()
        jobs = await _service(c).create(case, rounds.jobs_of(hit))
        return ApplyLimitOut(jobs=jobs, limit_hit=None, limit_extensions=n, confirm_payload=None, resume=None,
                             route=None)  # fmt: skip
    # "stop", a typed reply or anything else: answer with what was collected (nothing is lost)
    c.budget.allow_answer()
    return ApplyLimitOut(jobs=[], limit_hit=None, confirm_payload=None, resume=None, route=None)


def route_after_limit(state: TurnState) -> str:
    if state.get("route") == "interpret":
        return "interpret"
    return "next_round" if state.get("jobs") else "after_research"


@node("next_round", reads=NothingIn, writes=NothingOut)
async def next_round(inp: NothingIn, c: TurnContext) -> NothingOut:
    """A join point: the next gap round's jobs are fanned out from here (research.fan_out)."""
    return NothingOut()


@node("after_research", reads=AfterResearchIn, writes=AfterResearchOut)
async def after_research(inp: AfterResearchIn, c: TurnContext) -> AfterResearchOut:
    """The research done: its notices (incomplete jobs, areas short of data); a "find it" that found nothing more
    remembers the car and area so it is not offered again."""
    case = await c.case()
    notices, short = _service(c).conclude(case, inp.research_results, list(inp.notices), inp.language,
                                          WORDING)  # fmt: skip
    if not (inp.request_kind in ("research_more", "critique") and short):
        return AfterResearchOut(research_done=True, notices=notices, jobs=[])
    for k, a in short:  # "find it" found nothing more: remembered, not offered again for this car and area
        vid = next((x.variant_id for x in case.cars if x.key == k and x.variant_id), None)
        if vid and a not in case.find_tried.get(vid, []):
            case.find_tried.setdefault(vid, []).append(a)
    missed = ", ".join(f"{k} {a}" for k, a in short)
    await c.save_case(case, [f"searched deeper without the minimum: {missed}"], publish=False)
    return AfterResearchOut(research_done=True, notices=notices, jobs=[])


def _service(c: TurnContext) -> ResearchService:
    return ResearchService(c.ports, c.budget, c, c.chat_id, c.turn_id)
