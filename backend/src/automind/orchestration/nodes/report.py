"""REPORT, ANSWER_FROM_CONTEXT and ANSWER_GENERAL nodes.

Numbers come only from code (compose); the LLM explains and every number it writes is checked
by the guard (FR-031). A report records its fingerprint so an unchanged case is never re-reported
(FR-004).

Interim (US1): blocks come from the demo compose path with persona → demo profile mapping.
US3 (T056–T060) replaces this with criteria scores, persona block order and persona reporters.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from langgraph.runtime import Runtime

from automind.application import compose
from automind.application.usage import BudgetExceeded
from automind.domain import ask_value, profile_gaps
from automind.domain.casefile import CaseFile, Shown
from automind.domain.policy import fingerprint
from automind.orchestration import agents, outcomes
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

log = logging.getLogger(__name__)  # one logging stack: stdlib everywhere (spec 007 J, T079)


def _log_removed(c: TurnContext, where: str, n: int) -> None:
    """Sentences the checks removed are an operator signal, not a message to the user (reviewer 2026-11-03)."""
    if n:
        outcomes.note("guard_removed", n)  # spec 010 US1: class "bad text"
        log.info("guard.sentences_removed", extra={"where": where, "count": n, "chat_id": c.chat_id,
                                                   "turn_id": c.turn_id})  # fmt: skip


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
    again, dropped = check_numbers(again, allowed, len(comp.cars))
    still = report_violations(again, comp.check)
    return (drop_sentences(again, still), dropped + len(still)) if still else (again, dropped)


_PERSONA_CHIPS = ("PERFORMANCE", "BUYER", "EXPERT")
_ONCE = ("KM_PER_YEAR", "FAMILY_SIZE", "OWNERSHIP_YEARS", "PERSONA", "CONFIRM_PROFILE", "HOME_CHARGING")
_FAMILY_CHIP = {"SINGLE": "single", "COUPLE": "couple", "FAMILY": "kids"}


def _what(case: CaseFile, key: str, lang: str | None) -> str:
    p = case.profile
    if key == "family" and p.family:
        return t(f"family_{_FAMILY_CHIP[p.family]}", lang)
    if key == "driving_style" and p.driving_style:
        return t(f"style_{p.driving_style}", lang)
    if key == "usage":
        return ", ".join(u.lower() for u in case.usage)
    return str(getattr(p, key, "") or "")


def _confirm_inferred(
    case: CaseFile, comp: Any, blocks: list[dict[str, Any]], lang: str | None
) -> list[dict[str, Any]] | None:  # fmt: skip
    """Spec 007 J (T077): a guessed profile field that decides the winner is never applied silently. The verdict
    says what it assumes and what the result would be without it, and the user is asked to confirm (once; the
    note stays on every report until the field is stated). None when no guess decides the outcome."""
    if comp.outcome is None or len(comp.cars) < 2:
        return None
    flip = ask_value.inferred_flip(case, comp.outcome)
    if flip is None:
        return None
    key, (other_car, other_tie) = flip
    what = _what(case, key, lang)
    names = {car["variant"].id: compose.short_name(car["variant"]) for car in comp.cars}
    other = t("other_tie", lang) if other_tie or not other_car else t("other_wins", lang, car=names.get(other_car, ""))
    note = t("assume_note", lang, what=what, ev=case.profile.evidence.get(key, "…"), other=other)
    verdict = next((b for b in blocks if b.get("type") == "verdict"), None)
    if verdict is not None:
        verdict["profile_notes"] = [note, *verdict.get("profile_notes", [])]
    if "CONFIRM_PROFILE" in case.asked:
        return []
    case.asked.append("CONFIRM_PROFILE")
    if key == "family":
        items = [
            {"label": t(f"family_{x}", lang), "text": t(f"family_{x}", lang)} for x in ("single", "couple", "kids")
        ]
    elif key == "driving_style":
        items = [{"label": t(f"style_{x}", lang), "text": t(f"style_{x}", lang)} for x in ("CALM", "MIXED", "SPORTY")]
    else:
        yes = t("confirm_yes", lang, what=what)
        items = [{"label": yes, "text": yes}, {"label": t("confirm_no", lang), "text": t("confirm_no", lang)}]
    return [{"type": "quick_replies", "question": t("confirm_q", lang, what=what), "items": items}]


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
    elif kind == "HOME_CHARGING":
        items = [{"label": t(f"charge_{x}", lang), "text": t(f"charge_{x}", lang)} for x in ("YES", "WORK", "NO")]
    else:
        items = [
            {"label": t(f"family_{x}", lang), "text": t(f"family_{x}", lang)} for x in ("single", "couple", "kids")
        ]
    q = t(f"profile_{kind}", lang, km=f"{case.annual_km:,}", years=case.ownership_years or "")
    return [{"type": "quick_replies", "question": q, "items": items}]


def _mark_score_changes(case: CaseFile, blocks: list[dict[str, Any]]) -> None:
    """Annotate the criteria block with the change of each total and criterion score against the previous report,
    and remember these scores for the next one (spec 007 FR-013)."""
    crit = next((b for b in blocks if b.get("type") == "criteria_scores"), None)
    if crit is None:
        return
    now: dict[str, dict[str, float]] = {}
    for car in crit.get("cars", []):
        now[str(car.get("car_id"))] = _mark_car(car, case.last_scores.get(str(car.get("car_id"))))
    prev_weights = case.last_weights
    if prev_weights:
        for row in crit.get("criteria", []):
            row["delta"] = round(float(row["weight"]) - prev_weights.get(row["key"], 0.0), 1)
    case.last_scores = now
    case.last_weights = {row["key"]: float(row["weight"]) for row in crit.get("criteria", [])}


def _mark_car(car: dict[str, Any], before: dict[str, float] | None) -> dict[str, float]:
    parts = car.get("parts") or {}
    scores = {k: float(p["score"]) for k, p in parts.items() if p.get("score") is not None}
    if car.get("total") is not None:
        scores["_total"] = float(car["total"])
    if before is not None:
        if "_total" in scores and "_total" in before:
            car["delta"] = round(scores["_total"] - before["_total"], 1)
        for k, part in parts.items():
            if k in scores and k in before:
                part["delta"] = round(scores[k] - before[k], 1)
    return scores


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
        rescore = (state.get("decision") or {}).get("kind") == "RESCORE"
        if rescore:  # spec 007 FR-013: a panel edit; the blocks are recomputed, the text says only what changed
            changes = "; ".join(str(x) for x in ((state.get("preset") or {}).get("changes") or [])) or "the profile"
            request += (f"\nThe user changed in the case panel: {changes}. Do not write a full report. In 2-4 short "
                        "sentences say what this changed in the result: the weights, the scores and whether the winner "
                        "or the tie changed, and why, using only the facts.")  # fmt: skip
        if critique:  # spec 004 FR-021: rework with what the user disliked, and say what was done
            request += (f"\nThe user criticised the previous report: \"{state.get('user_text', '')}\". Rework it: go "
                        "deeper on what they ask for, use every meaningful difference, never apologise.")  # fmt: skip
        text = await _explain(c, "reporter", system, request, comp.facts)
        allowed = numbers_in(comp.facts) | numbers_in(comp.blocks) | numbers_in(_case_summary(case))
        text, dropped = check_numbers(text, allowed, len(case.cars))
        text, fixed = await _report_check(c, system, request, comp, text, allowed)
        _log_removed(c, "report", dropped + fixed)
        blocks = list(comp.blocks)
        _mark_score_changes(case, blocks)  # spec 007 FR-013: changed scores are highlighted
        if critique:
            text = _critique_lead(state, lang) + "\n\n" + text
        fp = fingerprint(case)
        case.shown.append(
            Shown(
                turn_seq=len(case.shown) + 1, fingerprint=fp, blocks=[b["type"] for b in blocks], persona=case.persona
            )
        )
        case.asked = [q for q in case.asked if q in _ONCE]  # profile questions: once
        confirm = _confirm_inferred(case, comp, blocks, lang)  # a guess that decides comes first (one question)
        if confirm is None:
            blocks += _profile_question(case, comp, lang, (c.ports.ref.profile_defaults or {}).get("probe"))
        else:
            blocks += confirm
        panel = next((b for b in blocks if b.get("type") == "data_panel"), None)
        if panel is not None:  # what the next "find it" is compared against (spec 004 FR-015)
            case.last_values = {x["car_key"]: int(x["values"]) for x in panel["cars"]}
        version = await save_case(c, case, [], publish=False)
        await c.status("done", "Done")
        # a rescore is a report too: its fingerprint is what the next "nothing new" is compared against
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
    text, dropped = check_numbers(text, numbers_in(facts), len(case.cars))
    if comp.check is not None:  # chat 5821ac77: never "the costlier car saves" in a follow-up either
        wrong = [v for v in report_violations(text, comp.check) if v.rule == "saving_costlier"]
        text, dropped = drop_sentences(text, wrong), dropped + len(wrong)
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
