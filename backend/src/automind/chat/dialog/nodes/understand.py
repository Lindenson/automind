"""Understanding nodes: load_case → interpret (the interpretation service: model or code) → apply_delta (code) →
assess (catalog) → policy (code)."""

from __future__ import annotations

from typing import Any, cast

from langgraph.runtime import Runtime

from automind.acquisition import api as acquisition
from automind.chat.application.services.feasibility import feasibility as fz_app
from automind.chat.application.services.identification import assessment, revalidation
from automind.chat.application.services.interpretation.contracts import (
    AppliedState,
    Interpretation,
    Preset,
    ReadState,
)
from automind.chat.application.services.interpretation.service import ApplyRequest, InterpretationService
from automind.chat.application.services.report.blocks.notice import notice
from automind.chat.dialog.context import ctx, current_year, history, intake_log, load_case, save_case
from automind.chat.dialog.nodes import feasibility as fz_nodes
from automind.chat.dialog.phrases import t
from automind.chat.dialog.policy import decide
from automind.chat.dialog.report_wording import WORDING
from automind.chat.dialog.runner import TurnContext
from automind.chat.dialog.state import PER_TURN_RESET, TurnState
from automind.chat.domain import intake
from automind.chat.domain.case import CaseFile
from automind.chat.domain.decision import CarState
from automind.shared.infrastructure.config.settings import settings
from automind.shared.research_order import plan as research_plan


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


async def assess_node(state: TurnState, runtime: Runtime[TurnContext]) -> dict[str, Any]:
    """Catalog lookup per car, auto-resolution, the case-driven research plan and its cost estimate."""
    c = ctx(runtime)
    _, case = await load_case(c)
    year = current_year(c)
    assessments: dict[str, dict[str, Any]] = {}
    changed: list[str] = []
    level, source = await revalidation.compare_level(case.cars)
    if (level, source) != (case.compare_level, case.compare_level_source):
        case.compare_level, case.compare_level_source = level, source  # type: ignore[assignment]
        changed.append(f"comparison level: {level.lower()}")
    for car in case.cars:
        reason = (
            await revalidation.revalidate(car, c.ports.ref, year)
            or await revalidation.revalidate_level(car, level)
            or await revalidation.split_by_gearbox(car, c.ports.ref)
        )
        if reason:
            changed.append(reason)
        a = await assessment.assess_car(car, c.ports.ref, year, level)
        if assessment.auto_resolve(car, a):
            changed.append(f"{car.key} → {car.label}")
        assessments[car.key] = a.model_dump(mode="json")
    out: dict[str, Any] = {}
    if changed:
        out["case_version"] = await save_case(c, case, changed)
    more = state.get("request_kind") in ("research_more", "critique") and not state.get("research_done")
    interp = state.get("interpretation") or {}
    plan = await _plan(
        c, case, research_more=more, focus=list(interp.get("focus_cars") or []),
        areas=list(interp.get("focus_areas") or []),
    )  # fmt: skip
    for key, a in assessments.items():
        car = case.car(key)
        a["state"]["data_fresh"] = bool(car.variant_id) and not any(j.car_key == key for j in plan.jobs)
    out["assessments"] = assessments
    out["research_plan"] = {
        "jobs": [[j.car_key, j.variant_id, j.area, j.fresh, j.escalate] for j in plan.jobs],
        "rounds": plan.rounds,
    }
    out["cost_estimate"] = await c.ports.estimator.estimate([(j.variant_id, j.area) for j in plan.jobs], plan.rounds)
    out["research_plan"]["key"] = research_plan.plan_key(plan)
    # Recomputed on every assess: the plan can grow inside a turn (a car confirmed after the first assess),
    # and a refusal of the smaller plan must not block research for the new one.
    out["research_declined"] = bool(plan.jobs) and case.declined_plan == out["research_plan"]["key"]
    store = c.ports.feasibility  # None: the feasibility checks are off
    if (
        store is not None
        and fz_app.has_constraints(case)
        and case.cars
        and not plan.jobs
        and all(x.variant_id for x in case.cars)
    ):
        out["feasibility"] = await fz_app.evaluate(
            case, c.ports.ref.feasibility, c.ports.ref.rates or {}, c.ports.clock.now().year, store
        )
    warn = [notice(_warning_text(w.kind, case.car(w.car_key).label or case.car(w.car_key).request_text), "warning")
            for w in plan.warnings]  # fmt: skip
    have = {n["text"] for n in state.get("notices", [])}
    if any(n["text"] not in have for n in warn):
        out["notices"] = [*state.get("notices", []), *(n for n in warn if n["text"] not in have)]
    return out


async def _plan(
    c: TurnContext, case: CaseFile, *, research_more: bool = False, focus: list[str] | None = None,
    areas: list[str] | None = None,
) -> research_plan.ResearchPlan:  # fmt: skip
    ok = [x for x in case.cars if x.variant_id and x.resolution in ("CONFIRMED", "AUTO_OK", "PROPOSED")]
    pts = await acquisition.powertrains([x.variant_id for x in ok if x.variant_id])
    cars = [
        research_plan.CarToPlan(key=x.key, variant_id=x.variant_id, condition=x.condition, age_years=x.age_years,
                                electrified=(pts.get(x.variant_id) or "").upper() in ("BEV", "PHEV", "EREV"))
        for x in ok
        if x.variant_id
    ]  # fmt: skip
    criteria = [p.criterion for p in case.priorities] + [k for k, w in case.weights.items() if w > 0]
    last = await acquisition.last_done([x.variant_id for x in cars])
    market = await c.ports.market_facts.done() if c.ports.market_facts is not None else None
    for x in cars:  # market-level areas: one date for every car (spec 006 US5)
        last.setdefault(x.variant_id, {}).pop("incentives", None)
        if market is not None:
            last[x.variant_id]["incentives"] = market
    budget_used = bool(case.budget.max_eur) and (
        case.budget.intent in ("USED", "ANY") or any(x.condition == "USED" for x in case.cars)
    )
    unmet = await acquisition.unmet_areas([x.variant_id for x in cars])
    force: dict[str, set[str]] = {}
    if research_more:  # the user asked to find what is missing: retry areas below their minimum now, deeper
        keys = set(focus or []) or {x.key for x in cars}
        wanted = set(areas or [])  # "find it" for named areas: research them even if their minimum was met
        force = {x.variant_id: (wanted or unmet.get(x.variant_id, set())) for x in cars if x.key in keys}
    days = int((c.ports.ref.registry or {}).get("unmet_registry_retry_days", research_plan.REGISTRY_RETRY_DAYS))
    return research_plan.plan(
        cars, persona=case.persona, criteria=criteria, depth="DEEP" if research_more else case.depth, last_done=last,
        now=c.ports.clock.now(), budget_used=budget_used, force=force, unmet=unmet,
        registry_done=await acquisition.registry_done([x.variant_id for x in cars]), registry_days=days,
    )  # fmt: skip


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
        feasibility_pending=fz_nodes.pending(case, state.get("feasibility")),
        confirm_threshold_eur=s.cost_confirm_threshold_eur,
        hard_cap_eur=s.cost_hard_cap_eur,
        intake_limits=_intake_limits(c),
        hops=int(state.get("hops") or 0),
    )
    return {"decision": action.model_dump(mode="json"), "action": action.kind, "hops": int(state.get("hops") or 0) + 1}


def _intake_limits(c: TurnContext) -> intake.Limits:
    lim = c.ports.ref.search.get("intake") or {}
    return intake.Limits(
        max_attempts_per_item=int(lim.get("max_attempts_per_item", 2)),
        max_attempts_per_car=int(lim.get("max_attempts_per_car", 4)),
        full_intake=bool(lim.get("full_intake", False)),
    )


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
