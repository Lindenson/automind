"""The text of a report or an answer (FR-031, spec 004 FR-012/FR-021): the writer is given the computed facts only
(no tools), every number it writes is checked against the facts and blocks, a sentence that contradicts the blocks
is regenerated once and then removed, and a critique gets a lead saying what was done about it."""

from __future__ import annotations

import json
import logging
from typing import Any

from automind.chat.application.services.report.contracts import Computed
from automind.chat.dialog import agents
from automind.chat.dialog import tracing as outcomes
from automind.chat.dialog.guard import check_numbers, drop_sentences, numbers_in, report_violations, violations_prompt
from automind.chat.dialog.phrases import t
from automind.chat.dialog.state import TurnState
from automind.chat.dialog.turn.context import TurnContext
from automind.chat.domain.case import CaseFile
from automind.shared.metering.usage import BudgetExceeded

log = logging.getLogger(__name__)  # one logging stack: stdlib everywhere (spec 007 J, T079)


async def write_report(c: TurnContext, state: TurnState, case: CaseFile, comp: Computed) -> str:
    """The reporter's text for this report: checked numbers, no contradiction of the blocks, a critique's lead."""
    name = agents.prompt_name("reporter", case.persona)
    system = c.ports.ref.prompts[name].format(
        persona=case.persona, case_summary=case_summary(case), language=state.get("language", "en")
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
    text = await explain(c, "reporter", system, request, comp.facts)
    allowed = numbers_in(comp.facts) | numbers_in(comp.blocks) | numbers_in(case_summary(case))
    text, dropped = check_numbers(text, allowed, len(case.cars))
    text, fixed = await report_check(c, system, request, comp, text, allowed)
    log_removed(c, "report", dropped + fixed)
    return critique_lead(state, state.get("language", "en")) + "\n\n" + text if critique else text


async def write_answer(c: TurnContext, state: TurnState, case: CaseFile, comp: Computed,
                       nothing_new: bool) -> tuple[str, int]:  # fmt: skip
    """The answerer's text from the validated data (ANSWER_FROM_CONTEXT) and the sentences the checks removed."""
    facts = {"nothing_new": nothing_new, "case": case_summary(case), "variants": [x.label for x in case.cars],
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
    return text, dropped


def case_summary(case: CaseFile) -> str:
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


def log_removed(c: TurnContext, where: str, n: int) -> None:
    """Sentences the checks removed are an operator signal, not a message to the user (reviewer 2026-11-03)."""
    if n:
        outcomes.note("guard_removed", n)  # spec 010 US1: class "bad text"
        log.info("guard.sentences_removed", extra={"where": where, "count": n, "chat_id": c.chat_id,
                                                   "turn_id": c.turn_id})  # fmt: skip


async def explain(c: TurnContext, role: str, system: str, request: str, facts: dict[str, Any]) -> str:
    """Analyst text from the computed facts only: verdict, insights, blocks and the ownership cost the user sees.
    No tools (reviewer 2026-11-03): with tools the reporter saw no insights, chose its own weights, mileage and
    chat id, and its tool outputs widened what the number check allowed beyond the blocks on screen."""
    return await c.ports.llm.text(
        role,
        system + "\nYou have no tools; use only the JSON facts provided.",
        request + "\n\nValidated facts JSON:\n" + json.dumps(facts, ensure_ascii=False, default=str),
    )


async def report_check(
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


def critique_lead(state: TurnState, lang: str | None) -> str:
    """What was done about the critique, by code (never only an apology)."""
    areas = sorted({str(r.get("area")) for r in state.get("research_results", []) if r.get("area")})
    if state.get("research_done") and areas:
        return t("critique_researched", lang, areas=", ".join(areas))
    what = " ".join(str(state.get("user_text") or "").split())[:80]
    return t("critique_reworked", lang, what=what)
