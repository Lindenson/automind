"""Understanding nodes: load_case → interpret (the interpretation service: model or code) → apply_delta (code) →
assess (the assessment service: catalogue, research plan, cost); the policy follows (nodes/policy.py)."""

from __future__ import annotations

from automind.chat.application.services.assessment import AssessmentService, CarsAssessed, PlanRequest
from automind.chat.application.services.interpretation.contracts import Interpretation
from automind.chat.application.services.interpretation.service import ApplyRequest, InterpretationService
from automind.chat.dialog.context import current_year, history, intake_log
from automind.chat.dialog.contract import Retry, node
from automind.chat.dialog.nodes.understand_io import (
    ApplyDeltaIn,
    ApplyDeltaOut,
    AssessIn,
    AssessOut,
    InterpretIn,
    InterpretOut,
    LoadCaseIn,
    LoadCaseOut,
)
from automind.chat.dialog.phrases import t
from automind.chat.dialog.report_wording import WORDING
from automind.chat.dialog.state import PER_TURN_RESET, TurnState
from automind.chat.dialog.turn.context import TurnContext
from automind.chat.dialog.understanding_shadow import read_with_shadow
from automind.chat.domain.case import CaseFile


@node("load_case", reads=LoadCaseIn, writes=LoadCaseOut)
async def load_case_node(inp: LoadCaseIn, c: TurnContext) -> LoadCaseOut:
    """The start of a turn: the turn's ids and the case version, every per-turn key reset."""
    version = await c.case_version()
    await c.status("understanding", "Understanding your message")
    return LoadCaseOut.model_validate({**PER_TURN_RESET, "chat_id": c.chat_id, "turn_id": c.turn_id,
                                       "case_version": version})  # fmt: skip


@node("interpret", reads=InterpretIn, writes=InterpretOut, retry=Retry.PROVIDER)
async def interpret_node(inp: InterpretIn, c: TurnContext) -> InterpretOut:
    """The message read into an interpretation (the interpretation service), or a question asked back; spec 013
    S3: the new understanding runs beside it in the shadow and is recorded (`understanding_shadow`)."""
    case, hist, text = await c.case(), await history(c), inp.user_text or ""
    reading = await read_with_shadow(c, case, hist, text, inp.preset,
                                     lambda: _service(c).read(case, hist, text, inp.preset))  # fmt: skip
    return InterpretOut.from_reading(reading, t(reading.ask, reading.language or inp.language) if reading.ask else "")


@node("apply_delta", reads=ApplyDeltaIn, writes=ApplyDeltaOut)
async def apply_delta_node(inp: ApplyDeltaIn, c: TurnContext) -> ApplyDeltaOut:
    """The interpretation applied to the case by code; the case is saved when something changed."""
    case = await c.case()
    i = Interpretation.model_validate(inp.interpretation)
    edit = (inp.preset or {}).get("kind") == "car_edit"  # the edit's label is not the person's words
    text = "" if edit else inp.user_text or ""
    option = (inp.preset or {}).get("option_id")  # spec 013 T013: a tapped chip's id
    applied = _service(c).apply(ApplyRequest(case, i, text, bool(inp.picked), current_year(c), option))
    if applied.ask is not None:  # the request stays the interpretation's (applied.request is i.request here)
        return ApplyDeltaOut(action="ASK", done=True, reply_text=t(applied.ask, i.language),
                             request_kind=applied.request)  # fmt: skip
    if applied.saved:
        await c.save_case(applied.case, applied.changes)
    return ApplyDeltaOut.from_applied(applied)


@node("assess", reads=AssessIn, writes=AssessOut)
async def assess_node(inp: AssessIn, c: TurnContext) -> AssessOut:
    """The case's cars assessed (the case saved when that changed it), then the research plan and its cost."""
    case = await c.case()
    service = AssessmentService(c.ports.ref, c.ports.research, c.ports.estimator, c.ports.clock, WORDING,
                                c.ports.market_facts, c.ports.feasibility)  # fmt: skip
    cars = await service.cars(case, current_year(c))
    if cars.changes:
        await c.save_case(case, cars.changes)
    planned = await service.plan(_plan_request(inp, case, cars))
    return AssessOut.from_planned(planned, inp.notices, assessed_version=await c.case_version())


def route_after_interpret(state: TurnState) -> str:
    return "end" if state.get("done") else "apply_delta"


def route_after_apply(state: TurnState) -> str:
    return "end" if state.get("done") else "assess"


def _service(c: TurnContext) -> InterpretationService:
    return InterpretationService(c.ports.llm, c.ports.ref, WORDING, intake_log(c))


def _plan_request(inp: AssessIn, case: CaseFile, cars: CarsAssessed) -> PlanRequest:
    """What to plan: "find it" or a critique researches more (once a turn), for the cars and areas it names."""
    interp = inp.interpretation or {}
    more = inp.request_kind in ("research_more", "critique") and not inp.research_done
    return PlanRequest(
        case, cars.assessments, research_more=more, focus=tuple(interp.get("focus_cars") or []),
        areas=tuple(interp.get("focus_areas") or []), shown=frozenset(n["text"] for n in inp.notices),
        checked=inp.feasibility,
    )  # fmt: skip
