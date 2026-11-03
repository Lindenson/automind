"""Understanding nodes: load_case → interpret (LLM) → apply_delta (code) → assess (catalog) → policy (code)."""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from automind.application import feasibility as fz_app
from automind.application import research, resolve
from automind.application.interpret import Interpretation, InterpretError, interpret
from automind.config import settings
from automind.domain import identification, intake, research_plan
from automind.domain.casefile import CaseFile, apply, apply_defaults
from automind.domain.policy import CarState, decide
from automind.orchestration import phrases
from automind.orchestration.nodes import feasibility as fz_nodes
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
    preset = state.get("preset")
    if preset:  # a button already knows the request ("find it"): no model call
        said = [m["text"] for m in await history(c) if m["role"] == "user"]
        lang = preset.get("language") or phrases.guess_language(said)
        i = Interpretation(
            request=preset.get("kind", "research_more"), language=lang,
            focus_cars=list(preset.get("focus_cars") or []), focus_areas=list(preset.get("areas") or []),
        )  # fmt: skip
        return {"interpretation": i.model_dump(mode="json"), "request_kind": i.request, "language": i.language}
    try:
        i = await interpret(c.ports.llm, c.ports.ref.prompts["interpreter"], case, await history(c), state["user_text"])
    except InterpretError:
        return {
            "action": "ASK",
            "done": True,
            "reply_text": t("rephrase", state.get("language")),
        }
    said = [m["text"] for m in await history(c) if m["role"] == "user"]
    if said and said[-1] == state["user_text"]:
        said = said[:-1]
    lang = phrases.stable_language(i.language, state["user_text"], said)
    if lang != i.language:
        i = i.model_copy(update={"language": lang})
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
    sp = i.delta.set_persona
    if sp is not None and i.persona_evidence and new.persona == sp.persona:  # the words the persona came from
        new.profile.evidence["persona"] = i.persona_evidence.strip()[:120]
    new = apply_defaults(new, c.ports.ref.profile_defaults)  # spec 007 FR-003: what is assumed is marked ASSUMED
    request = "choose_for_me" if phrases.choose_for_me(state.get("user_text")) else i.request
    pending_intake = case.pending is not None and case.pending.kind in _INTAKE_PENDING
    if pending_intake and request in ("general_question", "chitchat"):
        # spec 005 FR-022: while an intake step is pending, every reply is an intake answer, never generic chat
        request = "compare"
        changes += _brand_from_text(new, case, state.get("user_text") or "", c.ports.ref.makes)
    changes += _person_from_text(new, case, state.get("user_text") or "", c.ports.ref.regions)
    unclear = _not_understood(case, new, request)
    new, extra = _pending_answered(new, i, request)
    changes += extra
    out: dict[str, Any] = {"not_understood": unclear, "request_kind": request}
    if changes or new != case:
        version = await save_case(c, new, changes)
        return {
            **out,
            "case_version": version,
            "case_changed": bool(changes),
            "persona_changed": any(ch.startswith("persona:") for ch in changes),
        }
    return {**out, "case_changed": False}


_INTAKE_PENDING = ("QUESTIONS", "CONFIRM_VARIANTS", "CONFIRM_INTAKE")


def _person_from_text(new: CaseFile, before: CaseFile, text: str, regions: dict[str, Any]) -> list[str]:
    """Deterministic facts about the person and the cars from the user's own words (spec 005 R11): region and
    climate, a yearly distance range, and the answer to "new or used?" for every car still UNKNOWN."""
    log: list[str] = []
    p = new.profile
    if (r := intake.region_of(text, regions)) is not None and r[0] != p.region_code:
        p.region, p.region_code, p.climate = r[2][:60], r[0], r[1]  # type: ignore[assignment]
        p.evidence["region"] = r[2]
        log.append(f"region {r[2]} ({r[1].lower()} climate)")
    if (d := intake.parse_distance(text)) is not None and (d[0], d[1]) != (p.annual_km_min, p.annual_km_max):
        p.annual_km_min, p.annual_km_max = d
        new.annual_km, new.annual_km_stated = round((d[0] + d[1]) / 2 / 500) * 500, True
        p.evidence["annual_km"] = text[:120]
        log.append(f"{d[0]:,}–{d[1]:,} km a year" if d[0] != d[1] else f"{d[0]:,} km a year")
    asked_condition = before.pending is not None and any(it.get("kind") == "CONDITION" for it in before.pending.items)
    if asked_condition and (cond := intake.condition_of(text)) is not None:
        for car in new.cars:
            if car.condition == "UNKNOWN":
                car.condition = cond  # type: ignore[assignment]
                log.append(f"{car.key}: {cond.lower()}")
    return log


def _brand_from_text(new: CaseFile, before: CaseFile, text: str, reg: Any) -> list[str]:
    """ "BYD is Build Your Dream, Chinese": a brand explained by the user sets the make of the pending car."""
    make = reg.match_make(text) if reg is not None else None
    if not make or before.pending is None:
        return []
    keys = [str(it.get("car")) for it in before.pending.items if it.get("car")]
    out = []
    for car in new.cars:
        if car.key in keys and not car.make:
            car.make = make
            out.append(f"{car.key}: make {make}")
    return out


def _not_understood(before: CaseFile, after: CaseFile, request: str) -> list[str]:
    """Car keys whose pending question or variant proposal the message did not answer (spec 004 FR-031)."""
    p = before.pending
    if p is None or p.kind == "CONFIRM_COST":
        return []
    keys: list[str] = []
    for item in p.items:
        key = str(item.get("car") or "")
        kind = "CONFIRM_VARIANTS" if p.kind == "CONFIRM_VARIANTS" else str(item.get("kind") or "")
        if not key or kind not in (*identification.CAR_QUESTIONS, "CONFIRM_VARIANTS"):
            continue
        b = next((x for x in before.cars if x.key == key), None)
        a = next((x for x in after.cars if x.key == key), None)
        if not identification.answer_settles(kind, b, a, request) and key not in keys:
            keys.append(key)
    return keys


def _pending_answered(
    case: CaseFile, i: Interpretation, request: str | None = None, *, keep: bool = False
) -> tuple[CaseFile, list[str]]:
    """A message after a question clears it; a yes (or "choose for me") to proposed variants confirms them.
    A message that did not answer a car question keeps it open (`keep`), so it is asked again."""
    if case.pending is None:
        return case, []
    request = request or i.request
    c = case.model_copy(deep=True)
    log: list[str] = []
    if c.pending is not None and c.pending.kind == "CONFIRM_VARIANTS" and request in ("confirm_yes", "choose_for_me"):
        for car in c.cars:
            if car.resolution == "PROPOSED" and car.variant_id:
                car.resolution = "CONFIRMED"
                log.append(f"{car.key} confirmed: {car.label}")
    if c.pending is not None and c.pending.kind == "CONFIRM_VARIANTS" and request == "confirm_no":
        for car in c.cars:
            if car.resolution == "PROPOSED":
                car.variant_id, car.label, car.resolution = None, None, "UNRESOLVED"
    if not keep:
        c.pending = None
    return c, log


async def assess_node(state: TurnState, runtime: Runtime[TurnContext]) -> dict[str, Any]:
    """Catalog lookup per car, auto-resolution, the case-driven research plan and its cost estimate."""
    c = ctx(runtime)
    _, case = await load_case(c)
    year = current_year(c)
    assessments: dict[str, dict[str, Any]] = {}
    changed: list[str] = []
    level, source = await resolve.compare_level(case.cars)
    if (level, source) != (case.compare_level, case.compare_level_source):
        case.compare_level, case.compare_level_source = level, source  # type: ignore[assignment]
        changed.append(f"comparison level: {level.lower()}")
    for car in case.cars:
        reason = (
            await resolve.revalidate(car, c.ports.ref, year)
            or await resolve.revalidate_level(car, level)
            or await resolve.split_by_gearbox(car, c.ports.ref)
        )
        if reason:
            changed.append(reason)
        a = await resolve.assess_car(car, c.ports.ref, year, level)
        if resolve.auto_resolve(car, a):
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
        "jobs": [[j.car_key, j.variant_id, j.area, j.fresh] for j in plan.jobs],
        "rounds": plan.rounds,
    }
    out["cost_estimate"] = await c.ports.estimator.estimate([(j.variant_id, j.area) for j in plan.jobs], plan.rounds)
    out["research_plan"]["key"] = research_plan.plan_key(plan)
    # Recomputed on every assess: the plan can grow inside a turn (a car confirmed after the first assess),
    # and a refusal of the smaller plan must not block research for the new one.
    out["research_declined"] = bool(plan.jobs) and case.declined_plan == out["research_plan"]["key"]
    if fz_app.has_constraints(case) and case.cars and not plan.jobs and all(x.variant_id for x in case.cars):
        out["feasibility"] = await fz_app.evaluate(
            case, c.ports.ref.feasibility, c.ports.ref.rates or {}, c.ports.clock.now().year, c.ports.feasibility
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
    cars = [
        research_plan.CarToPlan(key=x.key, variant_id=x.variant_id, condition=x.condition, age_years=x.age_years)
        for x in case.cars
        if x.variant_id and x.resolution in ("CONFIRMED", "AUTO_OK", "PROPOSED")
    ]
    criteria = [p.criterion for p in case.priorities] + [k for k, w in case.weights.items() if w > 0]
    last = await research.last_done([x.variant_id for x in cars])
    budget_used = bool(case.budget.max_eur) and (
        case.budget.intent in ("USED", "ANY") or any(x.condition == "USED" for x in case.cars)
    )
    unmet = await research.unmet_areas([x.variant_id for x in cars])
    force: dict[str, set[str]] = {}
    if research_more:  # the user asked to find what is missing: retry areas below their minimum now, deeper
        keys = set(focus or []) or {x.key for x in cars}
        wanted = set(areas or [])  # "find it" for named areas: research them even if their minimum was met
        force = {x.variant_id: (wanted or unmet.get(x.variant_id, set())) for x in cars if x.key in keys}
    return research_plan.plan(
        cars, persona=case.persona, criteria=criteria, depth="DEEP" if research_more else case.depth, last_done=last,
        now=c.ports.clock.now(), budget_used=budget_used, force=force, unmet=unmet,
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
    )
    return {"decision": action.model_dump(mode="json"), "action": action.kind}


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
    }[state["decision"]["kind"]]
