"""Understanding nodes: load_case → interpret (LLM) → apply_delta (code) → assess (catalog) → policy (code)."""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from automind.application import research, resolve
from automind.application.interpret import Interpretation, InterpretError, interpret
from automind.config import settings
from automind.domain import research_plan
from automind.domain.casefile import CaseFile, apply
from automind.domain.policy import CarState, decide
from automind.orchestration.phrases import t
from automind.orchestration.runner import TurnContext
from automind.orchestration.state import PER_TURN_RESET, TurnState

from .common import ctx, current_year, history, load_case, notice, save_case


async def load_case_node(state: TurnState, runtime: Runtime[TurnContext]) -> dict[str, Any]:
    c = ctx(runtime)
    version, _ = await load_case(c)
    await c.status("understanding", "Understanding your message")
    return {**PER_TURN_RESET, "chat_id": c.chat_id, "turn_id": c.turn_id, "case_version": version}


async def interpret_node(state: TurnState, runtime: Runtime[TurnContext]) -> dict[str, Any]:
    c = ctx(runtime)
    _, case = await load_case(c)
    try:
        i = await interpret(c.ports.llm, c.ports.ref.prompts["interpreter"], case, await history(c), state["user_text"])
    except InterpretError:
        return {
            "action": "ASK",
            "done": True,
            "reply_text": t("rephrase", state.get("language")),
        }
    return {"interpretation": i.model_dump(mode="json"), "request_kind": i.request, "language": i.language}


async def apply_delta_node(state: TurnState, runtime: Runtime[TurnContext]) -> dict[str, Any]:
    c = ctx(runtime)
    _, case = await load_case(c)
    i = Interpretation.model_validate(state["interpretation"])  # type: ignore[typeddict-item]
    year = current_year(c)
    try:
        new, changes = apply(case, i.delta, current_year=year)
    except ValueError:
        return {"action": "ASK", "done": True, "reply_text": t("which_car", i.language)}
    new, extra = _pending_answered(new, i)
    changes += extra
    if changes or new != case:
        version = await save_case(c, new, changes)
        return {
            "case_version": version,
            "case_changed": bool(changes),
            "persona_changed": any(ch.startswith("persona:") for ch in changes),
        }
    return {"case_changed": False}


def _pending_answered(case: CaseFile, i: Interpretation) -> tuple[CaseFile, list[str]]:
    """A message after a question clears it; a yes to proposed variants confirms them."""
    if case.pending is None:
        return case, []
    c = case.model_copy(deep=True)
    log: list[str] = []
    if c.pending is not None and c.pending.kind == "CONFIRM_VARIANTS" and i.request == "confirm_yes":
        for car in c.cars:
            if car.resolution == "PROPOSED" and car.variant_id:
                car.resolution = "CONFIRMED"
                log.append(f"{car.key} confirmed: {car.label}")
    if c.pending is not None and c.pending.kind == "CONFIRM_VARIANTS" and i.request == "confirm_no":
        for car in c.cars:
            if car.resolution == "PROPOSED":
                car.variant_id, car.label, car.resolution = None, None, "UNRESOLVED"
    c.pending = None
    return c, log


async def assess_node(state: TurnState, runtime: Runtime[TurnContext]) -> dict[str, Any]:
    """Catalog lookup per car, auto-resolution, the case-driven research plan and its cost estimate."""
    c = ctx(runtime)
    _, case = await load_case(c)
    year = current_year(c)
    assessments: dict[str, dict[str, Any]] = {}
    changed: list[str] = []
    for car in case.cars:
        a = await resolve.assess_car(car, c.ports.ref, year)
        if resolve.auto_resolve(car, a):
            changed.append(f"{car.key} → {car.label}")
        assessments[car.key] = a.model_dump(mode="json")
    out: dict[str, Any] = {}
    if changed:
        out["case_version"] = await save_case(c, case, changed)
    plan = await _plan(c, case)
    for key, a in assessments.items():
        car = case.car(key)
        a["state"]["data_fresh"] = bool(car.variant_id) and not any(j.car_key == key for j in plan.jobs)
    out["assessments"] = assessments
    out["research_plan"] = {
        "jobs": [[j.car_key, j.variant_id, j.area] for j in plan.jobs],
        "rounds": plan.rounds,
    }
    out["cost_estimate"] = await c.ports.estimator.estimate([(j.variant_id, j.area) for j in plan.jobs], plan.rounds)
    out["research_plan"]["key"] = research_plan.plan_key(plan)
    if plan.jobs and case.declined_plan == out["research_plan"]["key"]:
        out["research_declined"] = True  # the user already said no to exactly this research
    warn = [notice(_warning_text(w.kind, case.car(w.car_key).label or case.car(w.car_key).request_text), "warning")
            for w in plan.warnings]  # fmt: skip
    have = {n["text"] for n in state.get("notices", [])}
    if any(n["text"] not in have for n in warn):
        out["notices"] = [*state.get("notices", []), *(n for n in warn if n["text"] not in have)]
    return out


async def _plan(c: TurnContext, case: CaseFile) -> research_plan.ResearchPlan:
    cars = [
        research_plan.CarToPlan(key=x.key, variant_id=x.variant_id, condition=x.condition, age_years=x.age_years)
        for x in case.cars
        if x.variant_id and x.resolution in ("CONFIRMED", "AUTO_OK", "PROPOSED")
    ]
    criteria = [p.criterion for p in case.priorities] + [k for k, w in case.weights.items() if w > 0]
    last = await research.last_done([x.variant_id for x in cars])
    return research_plan.plan(
        cars, persona=case.persona, criteria=criteria, depth=case.depth, last_done=last, now=c.ports.clock.now()
    )


def _warning_text(kind: str, label: str) -> str:
    if kind == "OLD_CAR":
        return f"{label}: older than 25 years — sources are scarce, several sections may show insufficient data."
    return f"{label}: not sold new in Spain — prices and specifications may refer to another market."


async def policy_node(state: TurnState, runtime: Runtime[TurnContext]) -> dict[str, Any]:
    c = ctx(runtime)
    _, case = await load_case(c)
    s = settings()
    states = {k: CarState.model_validate(a["state"]) for k, a in state.get("assessments", {}).items()}
    action = decide(
        case,
        state.get("request_kind") or "compare",  # type: ignore[arg-type]
        states,
        cost_estimate_eur=state.get("cost_estimate"),
        last_fingerprint=await c.ports.turns.last_report_fingerprint(c.chat_id),
        cost_approved=bool(state.get("cost_approved")),
        research_declined=bool(state.get("research_declined") or state.get("research_done")),
        case_changed=bool(state.get("case_changed", True)),
        confirm_threshold_eur=s.cost_confirm_threshold_eur,
        hard_cap_eur=s.cost_hard_cap_eur,
    )
    return {"decision": action.model_dump(mode="json"), "action": action.kind}


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
    }[state["decision"]["kind"]]
