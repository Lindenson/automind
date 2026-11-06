"""Understanding nodes: load_case → interpret (LLM) → apply_delta (code) → assess (catalog) → policy (code)."""

from __future__ import annotations

import re
from typing import Any

from langgraph.runtime import Runtime

from automind.acquisition import api as acquisition
from automind.chat.application.services.feasibility import feasibility as fz_app
from automind.chat.application.services.identification import resolve
from automind.chat.application.services.interpretation.interpret import Interpretation, InterpretError, interpret
from automind.chat.application.services.report import car_view
from automind.chat.dialog import phrases
from automind.chat.dialog.nodes import feasibility as fz_nodes
from automind.chat.dialog.nodes.common import ctx, current_year, history, load_case, notice, record_intake, save_case
from automind.chat.dialog.phrases import t
from automind.chat.dialog.runner import TurnContext
from automind.chat.dialog.state import PER_TURN_RESET, TurnState
from automind.chat.domain.case import CarRef, CaseDelta, CaseFile, Constraints, StatedEnergy, apply, apply_defaults
from automind.chat.domain.identification import identification
from automind.chat.domain.intake import intake
from automind.chat.domain.policy import CarState, decide
from automind.shared.infrastructure.config.settings import settings
from automind.shared.research_order import plan as research_plan
from automind.shared.vehicle.identity import parse_engine


async def load_case_node(state: TurnState, runtime: Runtime[TurnContext]) -> dict[str, Any]:
    c = ctx(runtime)
    version, _ = await load_case(c)
    await c.status("understanding", "Understanding your message")
    return {**PER_TURN_RESET, "chat_id": c.chat_id, "turn_id": c.turn_id, "case_version": version}


async def interpret_node(state: TurnState, runtime: Runtime[TurnContext]) -> dict[str, Any]:
    c = ctx(runtime)
    _, case = await load_case(c)
    preset = state.get("preset")
    if preset and preset.get("kind") == "car_edit":  # spec 010 FR-037: a structured car edit, applied by code
        return await _car_edit(c, case, preset)
    if preset:  # a button already knows the request ("find it"): no model call
        said = [m["text"] for m in await history(c) if m["role"] == "user"]
        lang = preset.get("language") or phrases.guess_language(said)
        i = Interpretation(
            request=preset.get("kind", "research_more"), language=lang,
            focus_cars=list(preset.get("focus_cars") or []), focus_areas=list(preset.get("areas") or []),
        )  # fmt: skip
        return {"interpretation": i.model_dump(mode="json"), "request_kind": i.request, "language": i.language}
    if _pick(case, state.get("user_text") or "") is not None:  # a tapped option: answered by code (spec 007 F)
        said = [m["text"] for m in await history(c) if m["role"] == "user"]
        i = Interpretation(request="compare", language=phrases.guess_language(said))
        return {"interpretation": i.model_dump(mode="json"), "request_kind": i.request, "language": i.language,
                "picked": True}  # fmt: skip
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


async def _car_edit(c: TurnContext, case: CaseFile, preset: dict[str, Any]) -> dict[str, Any]:
    """ "Change" on a car (engine, gearbox, trim, generation, not this car, remove): the delta is built by code and
    goes the normal way (apply_delta → identify → assess → policy); the interpreter is never called."""
    said = [m["text"] for m in await history(c) if m["role"] == "user"]
    lang = preset.get("language") or phrases.guess_language(said)
    key, field = str(preset.get("car_key") or ""), str(preset.get("field") or "")
    try:
        delta = car_view.edit_delta(case, key, field, str(preset.get("value") or ""), c.ports.ref.makes.match_make
                                    if c.ports.ref.makes is not None else None)  # fmt: skip
    except (ValueError, KeyError):
        return {"action": "ASK", "done": True, "reply_text": t("which_car", lang), "language": lang}
    await record_intake(c, "CARD_EDITED", key, field, source="car_edit")
    i = Interpretation(request="correction", language=lang, relation="correction", delta=delta)
    return {"interpretation": i.model_dump(mode="json"), "request_kind": i.request, "language": i.language}


async def apply_delta_node(state: TurnState, runtime: Runtime[TurnContext]) -> dict[str, Any]:
    c = ctx(runtime)
    _, case = await load_case(c)
    i = Interpretation.model_validate(state["interpretation"])  # type: ignore[typeddict-item]
    year = current_year(c)
    if (state.get("preset") or {}).get("kind") == "car_edit":  # the edit's label is not the user's words
        state = {**state, "user_text": ""}  # type: ignore[typeddict-item]
    picked = _pick(case, state.get("user_text") or "") if state.get("picked") else None
    try:
        new, changes = picked if picked is not None else apply(case, i.delta, current_year=year)
    except ValueError:
        return {"action": "ASK", "done": True, "reply_text": t("which_car", i.language)}
    changes += _make_to_choose_from(new, case, state.get("user_text") or "", c.ports.ref.makes)
    changes += intake.inherit_condition(case, new)
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
    if not new.cars and new.pending is None and request not in ("confirm_yes", "confirm_no", "rescore"):
        new, request, more = _cars_safety_net(new, i, state.get("user_text") or "", c.ports.ref.makes, year, request)
        changes += more
    changes += _person_from_text(new, case, state.get("user_text") or "", c.ports.ref.regions)
    changes += _energy_from_text(new, state.get("user_text") or "", c.ports.ref.makes)
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


def _pick(case: CaseFile, text: str) -> tuple[CaseFile, list[str]] | None:
    """The reply is one of the options offered under the pending question (spec 007 F)."""
    return intake.pick(case, text, gearbox_words=phrases.GEARBOX_WORDS, yes=phrases.yes_or_no(text) == "yes",
                       choose=phrases.choose_for_me(text) or phrases.go_ahead(text))  # fmt: skip


# "для замены моего", "вместо", "to replace my", "instead of", "para sustituir", "en lugar de"
_REPLACE = re.compile(r"замен|вместо|на смену|replac|instead of|sustitu|reemplaz|en lugar de|cambiar mi", re.I)
_OWN = re.compile(r"(?<!\w)(мо[йеёюяи]\w*|my|mine|mi|mis)(?!\w)", re.I)


def _makes_named(text: str, reg: Any) -> list[str]:
    """The makes the words name exactly (an alias or a transliteration, one or two words), in order; a make right
    after "my" / "моего" / "mi" is the user's own car and is left out."""
    names = getattr(reg, "names", None) or {}
    words = re.findall(r"[\w&-]+", text.lower())
    out: list[str] = []
    for i, w in enumerate(words):
        if any(_OWN.fullmatch(x) for x in words[max(0, i - 2) : i]):
            continue
        make = names.get(" ".join(words[i : i + 2])) or names.get(w)
        if make and make not in out:
            out.append(make)
    return out


def _make_to_choose_from(new: CaseFile, before: CaseFile, text: str, reg: Any) -> list[str]:
    """009 FR-022 (chat 20b5b7f9): "find me a Kia to replace my Prado 150". A make named without a model, next to a
    car the purchase replaces, is a make to choose from (candidates are proposed), not a car to ask "which model?"
    about; the car to replace is the user's own (used) car, compared with the candidates."""
    old = {c.key for c in before.cars}
    added = [c for c in new.cars if c.key not in old]
    # "my Toyota" is the user's own car, never the make to choose from
    bare = [c for c in added if c.make and not c.model and not c.replaced and not _OWN.search(c.request_text)]
    log: list[str] = []
    replacing = bool(_REPLACE.search(text)) or any(c.replaced for c in added)
    modelled = [c for c in added if c.model and c not in bare]
    if not new.wanted_make and replacing and modelled:
        # the make of a bare car, else a make the words name that no car of this message has (the interpreter
        # dropped the Kia and kept the Prado only)
        taken = {(c.make or "").lower() for c in modelled}
        free = [m for m in _makes_named(text, reg) if m.lower() not in taken]
        make = bare[0].make if bare else (free[0] if len(modelled) == 1 and free else None)
        if make:
            new.wanted_make = make
            log.append(f"make to choose from: {new.wanted_make}")
    if new.wanted_make:  # the make to choose from is not a car of its own
        drop = [c for c in bare if (c.make or "").lower() == new.wanted_make.lower()]
        new.cars = [c for c in new.cars if c not in drop]
        log += [f"{c.key} removed: {c.request_text} (a make to choose from)" for c in drop]
        if replacing and not any(c.replaced for c in new.cars):
            for c in added:
                if c in drop or not c.model or (c.make or "").lower() == new.wanted_make.lower():
                    continue
                c.replaced = True
                log.append(f"{c.key}: the car to replace")
    for c in added:
        if c.replaced and c.condition == "UNKNOWN":  # the user's own car is a used one
            c.condition = "USED"
            log.append(f"{c.key}: used (the user's own car)")
    return log


def _charging_from_text(new: CaseFile, text: str) -> list[str]:
    """Where the user can charge and their own electricity price, from their words (spec 006 R5, R7)."""
    log: list[str] = []
    p = new.profile
    if (ch := intake.charging_of(text)) is not None and ch[0] != p.home_charging:
        p.home_charging = ch[0]  # type: ignore[assignment]
        p.evidence["home_charging"] = ch[1]
        new.basis["home_charging"] = "STATED"
        log.append(f'charging: {ch[0].lower()} ("{ch[1]}")')
    if (pr := intake.electricity_price_of(text)) is not None:
        r = new.rates_override
        if pr[0] != r.home_electricity_eur_per_kwh or (pr[1] and not r.night_tariff):
            r.home_electricity_eur_per_kwh, r.night_tariff = pr[0], (pr[1] or r.night_tariff)
            log.append(f"electricity: €{pr[0]:.3f}/kWh (your price){' at night' if pr[1] else ''}")
    return log


_SENTENCE = re.compile(r"[.!?\n]")


def _car_named(case: CaseFile, segment: str, reg: Any) -> str | None:
    """The key of the case car the words name (make or model, any script), the last one named; None if none."""
    found: str | None = None
    models = [c.model for c in case.cars if c.model]
    for w in re.findall(r"[\w&-]{2,}", segment):
        make = reg.match_make(w) if reg is not None else None
        model = reg.match_model(w, models) if reg is not None and models and len(w) >= 3 else None
        for car in case.cars:
            if (model and car.model == model) or (make and car.make == make and not model):
                found = car.key
                if model:
                    break
    return found


def _energy_from_text(new: CaseFile, text: str, reg: Any) -> list[str]:
    """The user's own consumption figures ("в гибридном режиме 5,5 л"), each tied to the car named before it in
    the same sentence (or left to the one car it can apply to). The newest figure per car and kind wins."""
    log: list[str] = []
    prev = 0
    for f in intake.energy_figures_of(text):
        sentence = max((m.end() for m in _SENTENCE.finditer(text, 0, f.start)), default=0)
        key = _car_named(new, text[max(prev, sentence) : f.start], reg)
        prev = f.start
        item = StatedEnergy(kind=f.kind, value=f.value, words=f.words, car_key=key)
        new.stated_energy = [x for x in new.stated_energy if (x.kind, x.car_key) != (f.kind, key)] + [item]
        unit = {"FUEL": "l/100 km", "CS": "l/100 km with an empty battery", "KWH": "kWh/100 km",
                "RANGE": "km on electricity"}[f.kind]  # fmt: skip
        log.append(f'your figure{" for " + key if key else ""}: {f.value:g} {unit} ("{f.words}")')
    return log


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
    log += _charging_from_text(new, text)
    if not new.cars and (body := intake.body_of(text)) and body != new.wanted_body:  # spec 007 US7
        new.wanted_body = body  # type: ignore[assignment]
        log.append(f"body wanted: {body}")
    asked_condition = before.pending is not None and any(it.get("kind") == "CONDITION" for it in before.pending.items)
    if asked_condition and (cond := intake.condition_of(text)) is not None:
        for car in new.cars:
            if car.condition == "UNKNOWN":
                car.condition = cond  # type: ignore[assignment]
                log.append(f"{car.key}: {cond.lower()}")
    return log


def _cars_safety_net(new: CaseFile, i: Interpretation, text: str, reg: Any, year: int,
                     request: str) -> tuple[CaseFile, str, list[str]]:  # fmt: skip
    """Two named cars are a comparison even when the interpreter called the message a general question or
    returned a comparison without cars (live run 2026-11-04, twice)."""
    found = intake.cars_in_text(text, reg.match_make) if reg is not None else []
    if len(found) < 2:
        return new, request, []
    cond = intake.condition_of(text) or "UNKNOWN"
    refs = [CarRef(request_text=words, make=make, condition=cond,
                   constraints=Constraints(engine_hint=parse_engine(words))) for words, make in found[:3]]  # fmt: skip
    out, log = apply(new, CaseDelta(add_cars=refs), current_year=year)
    return out, "compare", ["cars from the user's words (the interpreter found none)", *log]


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
        "jobs": [[j.car_key, j.variant_id, j.area, j.fresh, j.escalate] for j in plan.jobs],
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
    market = await c.ports.market_facts.done() if getattr(c.ports, "market_facts", None) is not None else None
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
