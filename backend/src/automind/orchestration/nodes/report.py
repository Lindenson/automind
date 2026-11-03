"""REPORT, ANSWER_FROM_CONTEXT and ANSWER_GENERAL nodes.

Numbers come only from code (compose); the LLM explains and every number it writes is checked
by the guard (FR-031). A report records its fingerprint so an unchanged case is never re-reported
(FR-004).

Interim (US1): blocks come from the demo compose path with persona → demo profile mapping.
US3 (T056–T060) replaces this with criteria scores, persona block order and persona reporters.
"""

from __future__ import annotations

import json
from typing import Any

import structlog
from langgraph.runtime import Runtime

from automind.application import compose
from automind.application.usage import BudgetExceeded
from automind.domain import ask_value, profile_gaps
from automind.domain.casefile import CaseFile, Shown
from automind.domain.policy import fingerprint
from automind.orchestration import agents
from automind.orchestration.guard import (
    check_numbers,
    drop_sentences,
    numbers_in,
    report_violations,
    violations_prompt,
)
from automind.orchestration.phrases import t
from automind.orchestration.runner import TurnContext
from automind.orchestration.state import TurnState

from .common import ctx, history, load_case, save_case
from .compute import compute

log = structlog.get_logger()


def _log_removed(c: TurnContext, where: str, n: int) -> None:
    """Sentences the checks removed are an operator signal, not a message to the user (reviewer 2026-11-03)."""
    if n:
        log.info("guard.sentences_removed", where=where, count=n, chat_id=c.chat_id, turn_id=c.turn_id)


def _case_summary(case: CaseFile) -> str:
    bits = [f"persona {case.persona}"]
    if case.profile.age:
        bits.append(f"age {case.profile.age}")
    if case.usage:
        bits.append("usage " + ", ".join(case.usage))
    if case.priorities:
        bits.append("priorities " + ", ".join(f"{p.criterion} ({p.strength})" for p in case.priorities))
    if case.budget.max_eur:
        bits.append(f"budget up to €{case.budget.max_eur}")
    for car in case.cars:
        year = f", ~{car.year}" if car.year else ""
        bits.append(f"{car.key}: {car.label or car.request_text} [{car.condition.lower()}{year}]")
    return "; ".join(bits)


async def _explain(c: TurnContext, role: str, system: str, request: str, facts: dict[str, Any]) -> str:
    """Analyst text from the computed facts only: verdict, insights, blocks and the ownership cost the user sees.
    No tools (reviewer 2026-11-03): with tools the reporter saw no insights, chose its own weights, mileage and
    chat id, and its tool outputs widened what the number check allowed beyond the blocks on screen."""
    return await c.ports.llm.text(
        role,
        system + "\nYou have no tools; use only the JSON facts provided.",
        request + "\n\nValidated facts JSON:\n" + json.dumps(facts, ensure_ascii=False, default=str),
    )


async def _report_check(
    c: TurnContext, system: str, request: str, comp: Any, text: str, allowed: set[float]
) -> tuple[str, int]:
    """Text vs blocks (spec 004 FR-012): one regeneration with the violations listed; if the text still
    contradicts the blocks, the offending sentences are removed. Returns (text, sentences removed)."""
    if comp.check is None:
        return text, 0
    bad = report_violations(text, comp.check)
    if not bad:
        return text, 0
    await c.status("composing", f"Correcting {len(bad)} sentence(s) that contradict the data")
    try:
        again = await c.ports.llm.text(
            "reporter",
            system + "\nYou have no tools; use only the JSON facts provided.",
            request + "\n\n" + violations_prompt(bad) + "\n\nPrevious text:\n" + text
            + "\n\nValidated facts JSON:\n" + json.dumps(comp.facts, ensure_ascii=False, default=str),
        )  # fmt: skip
    except BudgetExceeded:
        raise
    except Exception:  # noqa: BLE001 - no second text: remove the offending sentences instead
        return drop_sentences(text, bad), len(bad)
    again, dropped = check_numbers(again, allowed)
    still = report_violations(again, comp.check)
    return (drop_sentences(again, still), dropped + len(still)) if still else (again, dropped)


_PERSONA_CHIPS = ("PERFORMANCE", "BUYER", "EXPERT")
_ONCE = ("KM_PER_YEAR", "FAMILY_SIZE", "OWNERSHIP_YEARS", "PERSONA")


def _profile_question(case: CaseFile, comp: Any, lang: str | None, probes: Any = None) -> list[dict[str, Any]]:
    """One question about the user, under the report and never blocking it, and only when the answer would change
    the winner or the tie on this data (spec 007 FR-006; spec 004 FR-018). The answer recomputes the report."""
    variants = [car["variant"] for car in comp.cars]
    if len(variants) < 2:
        return []
    kinds: list[str] = []
    if comp.outcome is not None:
        kinds = list(ask_value.questions(case, comp.outcome, probes or {}))
    if not kinds:
        gaps = profile_gaps.questions(case, [v.powertrain for v in variants], [v.vehicle_class for v in variants])
        kinds = [k for k in gaps if k == "FAMILY_SIZE"]
    if not kinds:
        return []
    kind = kinds[0]
    case.asked.append(kind)  # type: ignore[arg-type]
    if kind == "KM_PER_YEAR":
        items = [{"label": x, "text": x} for x in ("8,000 km", "15,000 km", "25,000 km", "40,000 km")]
    elif kind == "OWNERSHIP_YEARS":
        items = [{"label": t(f"years_{n}", lang), "text": t(f"years_{n}", lang)} for n in (3, 5, 8, 12)]
    elif kind == "PERSONA":
        items = [{"label": t(f"persona_{p}", lang), "text": t(f"persona_{p}", lang)} for p in _PERSONA_CHIPS]
    else:
        items = [
            {"label": t(f"family_{x}", lang), "text": t(f"family_{x}", lang)} for x in ("single", "couple", "kids")
        ]
    q = t(f"profile_{kind}", lang, km=f"{case.annual_km:,}", years=case.ownership_years or "")
    return [{"type": "quick_replies", "question": q, "items": items}]


def _critique_lead(state: TurnState, lang: str | None) -> str:
    """What was done about the critique, by code (never only an apology)."""
    areas = sorted({str(r.get("area")) for r in state.get("research_results", []) if r.get("area")})
    if state.get("research_done") and areas:
        return t("critique_researched", lang, areas=", ".join(areas))
    what = " ".join(str(state.get("user_text") or "").split())[:80]
    return t("critique_reworked", lang, what=what)


def make_report_node():  # noqa: ANN201
    async def report_node(state: TurnState, runtime: Runtime[TurnContext]) -> dict[str, Any]:
        c = ctx(runtime)
        _, case = await load_case(c)
        await c.status("computing", "Computing criteria scores, metrics and the drag race")
        lang = state.get("language", "en")
        comp = await compute(c, case, list(state.get("notices", [])), lang)
        await compose.persist_computations(
            c.turn_id,
            comp.tco,
            comp.cars,
            comp.race,
            case.rates_override.model_dump(exclude_none=True),
            case.prediction.model_dump() if case.prediction else None,
            {x.variant_id: x.mileage_km for x in case.cars if x.variant_id},
        )
        await c.status("composing", "Writing the conclusion for you")
        name = agents.prompt_name("reporter", case.persona)
        system = c.ports.ref.prompts[name].format(
            persona=case.persona, case_summary=_case_summary(case), language=state.get("language", "en")
        )
        car_list = [x["variant"].label for x in comp.cars]
        request = f"User message: {state.get('user_text', '')}\nCars: {json.dumps(car_list, ensure_ascii=False)}"
        critique = state.get("request_kind") == "critique"
        if critique:  # spec 004 FR-021: rework with what the user disliked, and say what was done
            request += (f"\nThe user criticised the previous report: \"{state.get('user_text', '')}\". Rework it: go "
                        "deeper on what they ask for, use every meaningful difference, never apologise.")  # fmt: skip
        text = await _explain(c, "reporter", system, request, comp.facts)
        allowed = numbers_in(comp.facts) | numbers_in(comp.blocks) | numbers_in(_case_summary(case))
        text, dropped = check_numbers(text, allowed)
        text, fixed = await _report_check(c, system, request, comp, text, allowed)
        _log_removed(c, "report", dropped + fixed)
        blocks = list(comp.blocks)
        if critique:
            text = _critique_lead(state, lang) + "\n\n" + text
        fp = fingerprint(case)
        case.shown.append(
            Shown(
                turn_seq=len(case.shown) + 1, fingerprint=fp, blocks=[b["type"] for b in blocks], persona=case.persona
            )
        )
        case.asked = [q for q in case.asked if q in _ONCE]  # profile questions: once
        blocks += _profile_question(case, comp, lang, (c.ports.ref.profile_defaults or {}).get("probe"))
        panel = next((b for b in blocks if b.get("type") == "data_panel"), None)
        if panel is not None:  # what the next "find it" is compared against (spec 004 FR-015)
            case.last_values = {x["car_key"]: int(x["values"]) for x in panel["cars"]}
        version = await save_case(c, case, [], publish=False)
        await c.status("done", "Done")
        return {"reply_text": text, "blocks": blocks, "action": "REPORT", "fingerprint": fp, "case_version": version}

    return report_node


async def answer_node(state: TurnState, runtime: Runtime[TurnContext]) -> dict[str, Any]:
    """ANSWER_FROM_CONTEXT: recompute from cached data, no research (FR-004, FR-029).

    A weights change shows the recomputed criteria scores; "nothing new" sends no blocks.
    """
    c = ctx(runtime)
    _, case = await load_case(c)
    nothing_new = bool(state["decision"].get("nothing_new"))
    comp = await compute(c, case, list(state.get("notices", [])), state.get("language", "en"))
    if state.get("case_changed") and case.race_settings is not None:  # a new race: keep it reproducible
        await compose.persist_computations(
            c.turn_id, [], comp.cars, comp.race, {}, case.prediction.model_dump() if case.prediction else None, {}
        )
    facts = {"nothing_new": nothing_new, "case": _case_summary(case), "variants": [x.label for x in case.cars],
             **comp.facts}  # fmt: skip
    await c.status("composing", "Answering from the validated data")
    system = c.ports.ref.prompts["answerer"].format(language=state.get("language", "en"))
    text = await c.ports.llm.text(
        "answerer",
        system,
        f"User message: {state.get('user_text', '')}\n\nFacts JSON:\n"
        + json.dumps(facts, ensure_ascii=False, default=str),
    )
    text, dropped = check_numbers(text, numbers_in(facts))
    last = case.shown[-1].persona if case.shown else None
    persona_changed = bool(state.get("persona_changed")) or (last is not None and last != case.persona)
    blocks: list[dict[str, Any]] = [] if nothing_new else _changed_blocks(state, comp.blocks, persona_changed)
    if persona_changed and not nothing_new:  # the reordered report was shown: later follow-ups are short again
        case.shown.append(
            Shown(
                turn_seq=len(case.shown) + 1,
                fingerprint=fingerprint(case),
                blocks=[b["type"] for b in blocks],
                persona=case.persona,
            )
        )
        await save_case(c, case, [], publish=False)
    _log_removed(c, "answer", dropped)
    await c.status("done", "Done")
    return {"reply_text": text, "blocks": blocks, "action": "ANSWER_FROM_CONTEXT"}


def _changed_blocks(state: TurnState, blocks: list[dict[str, Any]], persona_changed: bool) -> list[dict[str, Any]]:
    """For a weights change or a follow-up, show the recomputed scores (and warnings), not the whole report."""
    if persona_changed:
        return blocks  # a new persona sees the whole report in its own order (FR-030)
    keep = {"criteria_scores"} if state.get("request_kind") == "weights_change" else {"criteria_scores", "race_chart"}
    return [b for b in blocks if b.get("type") in keep or (b.get("type") == "notice" and b.get("level") == "warning")]


async def general_node(state: TurnState, runtime: Runtime[TurnContext]) -> dict[str, Any]:
    c = ctx(runtime)
    await c.status("composing", "Answering")
    hist = "\n".join(f"{m['role']}: {m['text'][:300]}" for m in (await history(c))[-4:])
    text = await c.ports.llm.text(
        "general",
        c.ports.ref.prompts["general"].format(language=state.get("language", "en")),
        f"{hist}\nuser: {state.get('user_text', '')}",
    )
    await c.status("done", "Done")
    return {"reply_text": text, "blocks": [], "action": "ANSWER_GENERAL"}
