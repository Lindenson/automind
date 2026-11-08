"""Understanding nodes: load_case → interpret (the interpretation service: model or code) → apply_delta (code) →
assess (the assessment service: catalogue, research plan, cost) → policy (code)."""

from __future__ import annotations

from typing import Any, TypedDict, cast

from langgraph.runtime import Runtime

from automind.chat.application.services.assessment import AssessmentService, CarsAssessed, PlanRequest
from automind.chat.application.services.assessment.contracts import AssessedState
from automind.chat.application.services.interpretation.contracts import (
    AppliedState,
    Interpretation,
    Preset,
    ReadState,
)
from automind.chat.application.services.interpretation.service import ApplyRequest, InterpretationService
from automind.chat.dialog.context import ctx, current_year, history, intake_log, load_case, save_case
from automind.chat.dialog.nodes import feasibility as fz_nodes
from automind.chat.dialog.phrases import t
from automind.chat.dialog.policy import decide
from automind.chat.dialog.report_wording import WORDING
from automind.chat.dialog.state import PER_TURN_RESET, DecisionState, TurnState
from automind.chat.dialog.turn.context import TurnContext
from automind.chat.domain import intake
from automind.chat.domain.case import CaseFile
from automind.chat.domain.decision import CarState
from automind.shared.infrastructure.config.settings import settings


class PolicyState(TypedDict):
    """What the policy writes into the turn state."""

    decision: DecisionState
    action: str
    hops: int


async def load_case_node(state: TurnState, runtime: Runtime[TurnContext]) -> dict[str, Any]:
    c = ctx(runtime)
    version, _ = await load_case(c)
    await c.status("understanding", "Understanding your message")
    return {**PER_TURN_RESET, "chat_id": c.chat_id, "turn_id": c.turn_id, "case_version": version}


async def interpret_node(state: TurnState, runtime: Runtime[TurnContext]) -> ReadState:
    """The message read into an interpretation (the interpretation service), or a question asked back."""
    c = ctx(runtime)
    _, case = await load_case(c)
    preset = cast(Preset | None, state.get("preset"))
    reading = await _service(c).read(case, await history(c), state.get("user_text") or "", preset)
    return reading.to_state(t(reading.ask, reading.language or state.get("language")) if reading.ask else "")


async def apply_delta_node(state: TurnState, runtime: Runtime[TurnContext]) -> AppliedState:
    """The interpretation applied to the case by code; the case is saved when something changed."""
    c = ctx(runtime)
    _, case = await load_case(c)
    i = Interpretation.model_validate(state.get("interpretation"))
    edit = (state.get("preset") or {}).get("kind") == "car_edit"  # the edit's label is not the person's words
    text = "" if edit else state.get("user_text") or ""
    applied = _service(c).apply(ApplyRequest(case, i, text, bool(state.get("picked")), current_year(c)))
    if applied.ask is not None:
        return {"action": "ASK", "done": True, "reply_text": t(applied.ask, i.language)}
    version = await save_case(c, applied.case, applied.changes) if applied.saved else None
    return applied.to_state(version)


def _service(c: TurnContext) -> InterpretationService:
    return InterpretationService(c.ports.llm, c.ports.ref, WORDING, intake_log(c))


async def assess_node(state: TurnState, runtime: Runtime[TurnContext]) -> AssessedState:
    """The case's cars assessed (the case saved when that changed it), then the research plan and its cost."""
    c = ctx(runtime)
    _, case = await load_case(c)
    service = AssessmentService(c.ports.ref, c.ports.research, c.ports.estimator, c.ports.clock, WORDING,
                                c.ports.market_facts, c.ports.feasibility)  # fmt: skip
    cars = await service.cars(case, current_year(c))
    version = await save_case(c, case, cars.changes) if cars.changes else None
    out = (await service.plan(_plan_request(state, case, cars))).to_state(state.get("notices", []))
    if version is not None:
        out["case_version"] = version
    return out


def _plan_request(state: TurnState, case: CaseFile, cars: CarsAssessed) -> PlanRequest:
    """What to plan: "find it" or a critique researches more (once a turn), for the cars and areas it names."""
    interp = state.get("interpretation") or {}
    more = state.get("request_kind") in ("research_more", "critique") and not state.get("research_done")
    return PlanRequest(
        case, cars.assessments, research_more=more, focus=tuple(interp.get("focus_cars") or []),
        areas=tuple(interp.get("focus_areas") or []), shown=frozenset(n["text"] for n in state.get("notices", [])),
    )  # fmt: skip


async def policy_node(state: TurnState, runtime: Runtime[TurnContext]) -> PolicyState:
    """The policy's decision for this pass over the case and the assessed cars (spec 007 FR-027: passes counted)."""
    c = ctx(runtime)
    _, case = await load_case(c)
    s = settings()
    hops = int(state.get("hops") or 0)
    action = decide(
        case,
        state.get("request_kind") or "compare",
        {k: CarState.model_validate(a["state"]) for k, a in state.get("assessments", {}).items()},
        cost_estimate_eur=state.get("cost_estimate"),
        last_fingerprint=await c.ports.turns.last_report_fingerprint(c.chat_id),
        cost_approved=bool(state.get("cost_approved")),
        research_declined=bool(state.get("research_declined") or state.get("research_done")),
        case_changed=bool(state.get("case_changed", True)),
        feasibility_pending=fz_nodes.pending(case, state.get("feasibility")),
        confirm_threshold_eur=s.cost_confirm_threshold_eur,
        hard_cap_eur=s.cost_hard_cap_eur,
        intake_limits=intake.Limits.from_config(c.ports.ref.search.get("intake") or {}),
        hops=hops,
    )
    decision = cast(DecisionState, action.model_dump(mode="json"))  # the Action as plain data, field for field
    return {"decision": decision, "action": action.kind, "hops": hops + 1}


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
