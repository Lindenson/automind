"""Understanding nodes: load_case → interpret (the interpretation service: model or code) → apply_delta (code) →
assess (the assessment service: catalogue, research plan, cost) → policy (code)."""

from __future__ import annotations

from typing import cast

from automind.chat.application.services.assessment import AssessmentService, CarsAssessed, PlanRequest
from automind.chat.application.services.interpretation.contracts import Interpretation
from automind.chat.application.services.interpretation.service import ApplyRequest, InterpretationService
from automind.chat.dialog.context import current_year, history, intake_log, load_case, save_case
from automind.chat.dialog.contract import Retry, node
from automind.chat.dialog.nodes import feasibility as fz_nodes
from automind.chat.dialog.nodes.understand_io import (
    ApplyDeltaIn,
    ApplyDeltaOut,
    AssessIn,
    AssessOut,
    InterpretIn,
    InterpretOut,
    LoadCaseIn,
    LoadCaseOut,
    PolicyIn,
    PolicyOut,
)
from automind.chat.dialog.phrases import t
from automind.chat.dialog.policy import decide
from automind.chat.dialog.report_wording import WORDING
from automind.chat.dialog.state import PER_TURN_RESET, DecisionState, TurnState
from automind.chat.dialog.turn.context import TurnContext
from automind.chat.domain import intake
from automind.chat.domain.case import CaseFile
from automind.chat.domain.decision import CarState
from automind.shared.infrastructure.config.settings import settings


@node("load_case", reads=LoadCaseIn, writes=LoadCaseOut)
async def load_case_node(inp: LoadCaseIn, c: TurnContext) -> LoadCaseOut:
    """The start of a turn: the turn's ids and the case version, every per-turn key reset."""
    version, _ = await load_case(c)
    await c.status("understanding", "Understanding your message")
    return LoadCaseOut.model_validate({**PER_TURN_RESET, "chat_id": c.chat_id, "turn_id": c.turn_id,
                                       "case_version": version})  # fmt: skip


@node("interpret", reads=InterpretIn, writes=InterpretOut, retry=Retry.PROVIDER)
async def interpret_node(inp: InterpretIn, c: TurnContext) -> InterpretOut:
    """The message read into an interpretation (the interpretation service), or a question asked back."""
    _, case = await load_case(c)
    reading = await _service(c).read(case, await history(c), inp.user_text or "", inp.preset)
    return InterpretOut.from_reading(reading, t(reading.ask, reading.language or inp.language) if reading.ask else "")


@node("apply_delta", reads=ApplyDeltaIn, writes=ApplyDeltaOut)
async def apply_delta_node(inp: ApplyDeltaIn, c: TurnContext) -> ApplyDeltaOut:
    """The interpretation applied to the case by code; the case is saved when something changed."""
    _, case = await load_case(c)
    i = Interpretation.model_validate(inp.interpretation)
    edit = (inp.preset or {}).get("kind") == "car_edit"  # the edit's label is not the person's words
    text = "" if edit else inp.user_text or ""
    option = (inp.preset or {}).get("option_id")  # spec 013 T013: a tapped chip's id
    applied = _service(c).apply(ApplyRequest(case, i, text, bool(inp.picked), current_year(c), option))
    if applied.ask is not None:  # the request stays the interpretation's (applied.request is i.request here)
        return ApplyDeltaOut(action="ASK", done=True, reply_text=t(applied.ask, i.language),
                             request_kind=applied.request)  # fmt: skip
    version = await save_case(c, applied.case, applied.changes) if applied.saved else None
    return ApplyDeltaOut.from_applied(applied, version)


@node("assess", reads=AssessIn, writes=AssessOut)
async def assess_node(inp: AssessIn, c: TurnContext) -> AssessOut:
    """The case's cars assessed (the case saved when that changed it), then the research plan and its cost."""
    _, case = await load_case(c)
    service = AssessmentService(c.ports.ref, c.ports.research, c.ports.estimator, c.ports.clock, WORDING,
                                c.ports.market_facts, c.ports.feasibility)  # fmt: skip
    cars = await service.cars(case, current_year(c))
    version = await save_case(c, case, cars.changes) if cars.changes else None
    return AssessOut.from_planned(await service.plan(_plan_request(inp, case, cars)), inp.notices, version)


@node("policy", reads=PolicyIn, writes=PolicyOut)
async def policy_node(inp: PolicyIn, c: TurnContext) -> PolicyOut:
    """The policy's decision for this pass over the case and the assessed cars (spec 007 FR-027: passes counted)."""
    _, case = await load_case(c)
    s = settings()
    hops = int(inp.hops or 0)
    action = decide(
        case,
        inp.request_kind or "compare",
        {k: CarState.model_validate(a["state"]) for k, a in inp.assessments.items()},
        cost_estimate_eur=inp.cost_estimate,
        last_fingerprint=await c.ports.turns.last_report_fingerprint(c.chat_id),
        cost_approved=bool(inp.cost_approved),
        research_declined=bool(inp.research_declined or inp.research_done),
        case_changed=bool(inp.case_changed),
        feasibility_pending=fz_nodes.pending(case, inp.feasibility),
        confirm_threshold_eur=s.cost_confirm_threshold_eur,
        hard_cap_eur=s.cost_hard_cap_eur,
        intake_limits=intake.Limits.from_config(c.ports.ref.search.get("intake") or {}),
        hops=hops,
    )
    decision = cast(DecisionState, action.model_dump(mode="json"))  # the Action as plain data, field for field
    return PolicyOut(decision=decision, action=action.kind, hops=hops + 1)


def route_after_interpret(state: TurnState) -> str:
    return "end" if state.get("done") else "apply_delta"


def route_after_apply(state: TurnState) -> str:
    return "end" if state.get("done") else "assess"


def route_policy(state: TurnState) -> str:
    return {
        "ANSWER_GENERAL": "general",
        "ASK": "ask",
        "CONFIRM_VARIANTS": "prepare_variants",
        "CONFIRM_COST": "prepare_cost",
        "RESEARCH": "plan_research",
        "ANSWER_FROM_CONTEXT": "answer",
        "REPORT": "report",
        "RESCORE": "report",  # spec 007: the report node recomputes and says what changed
        "FEASIBILITY": "prepare_feasibility",
        "CONFIRM_INTAKE": "prepare_intake",
        "SELECT_CANDIDATES": "select_candidates",
    }[state["decision"]["kind"]]


def _service(c: TurnContext) -> InterpretationService:
    return InterpretationService(c.ports.llm, c.ports.ref, WORDING, intake_log(c))


def _plan_request(inp: AssessIn, case: CaseFile, cars: CarsAssessed) -> PlanRequest:
    """What to plan: "find it" or a critique researches more (once a turn), for the cars and areas it names."""
    interp = inp.interpretation or {}
    more = inp.request_kind in ("research_more", "critique") and not inp.research_done
    return PlanRequest(
        case, cars.assessments, research_more=more, focus=tuple(interp.get("focus_cars") or []),
        areas=tuple(interp.get("focus_areas") or []), shown=frozenset(n["text"] for n in inp.notices),
    )  # fmt: skip
