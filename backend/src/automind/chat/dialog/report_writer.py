"""The text of a report or an answer (FR-031, spec 004 FR-012/FR-021): the writer is given the computed facts only
(no tools), every number it writes is checked against the facts and blocks, a sentence that contradicts the blocks
is regenerated once and then removed, and a critique gets a lead saying what was done about it.

Report and answer run the same check (spec 016 T306). The regeneration's failures: a budget stop propagates; a
provider that is down or a transient failure (`ProviderUnavailable`, `provider_failure.TRANSIENT`) removes the
offending sentences instead; any other error propagates and fails the turn (T305). A removal is logged, counted and
said to the person in one quiet line (T307)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from automind.chat.application.services.report.contracts import CheckInput, Computed
from automind.chat.dialog import agents
from automind.chat.dialog import tracing as outcomes
from automind.chat.dialog.guard import check_numbers, drop_sentences, numbers_in, report_violations, violations_prompt
from automind.chat.dialog.nodes.report_io import ComposeIn
from automind.chat.dialog.phrases import t
from automind.chat.dialog.turn.context import TurnContext
from automind.chat.domain.case import CaseFile
from automind.shared.contracts.json import JsonObject
from automind.shared.contracts.provider_failure import TRANSIENT, ProviderUnavailable, classify

log = logging.getLogger(__name__)  # one logging stack: stdlib everywhere (spec 007 J, T079)


async def write_report(c: TurnContext, inp: ComposeIn, case: CaseFile, comp: Computed) -> str:
    """The reporter's text for this report: checked numbers, no contradiction of the blocks, a critique's lead."""
    name = agents.prompt_name("reporter", case.persona)
    system = c.ports.ref.prompts[name].format(
        persona=case.persona, case_summary=case_summary(case), language=inp.language
    )
    car_list = [x["variant"].label for x in comp.cars]
    request = f"User message: {inp.user_text}\nCars: {json.dumps(car_list, ensure_ascii=False)}"
    critique = inp.request_kind == "critique"
    rescore = (inp.decision or {}).get("kind") == "RESCORE"
    if rescore:  # spec 007 FR-013: a panel edit; the blocks are recomputed, the text says only what changed
        changes = "; ".join(str(x) for x in ((inp.preset or {}).get("changes") or [])) or "the profile"
        request += (f"\nThe user changed in the case panel: {changes}. Do not write a full report. In 2-4 short "
                    "sentences say what this changed in the result: the weights, the scores and whether the winner "
                    "or the tie changed, and why, using only the facts.")  # fmt: skip
    if critique:  # spec 004 FR-021: rework with what the user disliked, and say what was done
        request += (f"\nThe user criticised the previous report: \"{inp.user_text}\". Rework it: go "
                    "deeper on what they ask for, use every meaningful difference, never apologise.")  # fmt: skip
    text = await explain(c, "reporter", system, request, comp.facts)
    allowed = numbers_in(comp.facts) | numbers_in(comp.blocks) | numbers_in(case_summary(case))
    text, dropped = check_numbers(text, allowed, len(case.cars))
    writing = Writing("reporter", system, request, comp.facts, comp.check, allowed, len(case.cars))
    text, fixed = await report_check(c, writing, text)
    log_removed(c, "report", dropped + fixed)
    text = with_notice(text, dropped + fixed, inp.language)
    return critique_lead(inp, inp.language) + "\n\n" + text if critique else text


async def write_answer(c: TurnContext, inp: ComposeIn, case: CaseFile, comp: Computed,
                       nothing_new: bool) -> tuple[str, int]:  # fmt: skip
    """The answerer's text from the validated data (ANSWER_FROM_CONTEXT) and the sentences the checks removed."""
    facts = {"nothing_new": nothing_new, "case": case_summary(case), "variants": [x.label for x in case.cars],
             **comp.facts}  # fmt: skip
    await c.status("composing", "Answering from the validated data")
    system = c.ports.ref.prompts["answerer"].format(language=inp.language)
    request = f"User message: {inp.user_text}"
    text = await c.ports.llm.text(
        "answerer", system, request + "\n\nFacts JSON:\n" + json.dumps(facts, ensure_ascii=False, default=str)
    )
    allowed = numbers_in(facts)
    text, dropped = check_numbers(text, allowed, len(case.cars))
    writing = Writing("answerer", system, request, facts, comp.check, allowed, len(case.cars))
    text, fixed = await report_check(c, writing, text)  # spec 016 T306: all four rules, as the report
    return with_notice(text, dropped + fixed, inp.language), dropped + fixed


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


def with_notice(text: str, removed: int, lang: str | None) -> str:
    """`text` with one quiet line saying that sentences the data did not support were removed (spec 016 D3)."""
    return f"{text}\n\n{t('guard_removed', lang)}" if removed else text


def log_removed(c: TurnContext, where: str, n: int) -> None:
    """Sentences the checks removed are an operator signal, not a message to the user (reviewer 2026-11-03)."""
    if n:
        outcomes.note("guard_removed", n)  # spec 010 US1: class "bad text"
        log.info("guard.sentences_removed", extra={"where": where, "count": n, "chat_id": c.chat_id,
                                                   "turn_id": c.turn_id})  # fmt: skip


async def explain(c: TurnContext, role: str, system: str, request: str, facts: JsonObject) -> str:
    """Analyst text from the computed facts only: verdict, insights, blocks and the ownership cost the user sees.
    No tools (reviewer 2026-11-03): with tools the reporter saw no insights, chose its own weights, mileage and
    chat id, and its tool outputs widened what the number check allowed beyond the blocks on screen."""
    return await c.ports.llm.text(
        role,
        system + "\nYou have no tools; use only the JSON facts provided.",
        request + "\n\nValidated facts JSON:\n" + json.dumps(facts, ensure_ascii=False, default=str),
    )


@dataclass(frozen=True)
class Writing:
    """What one text was written from: the role and prompt, the request, the facts it may use, the check of its
    conclusions (None: none), the numbers it may write and the number of cars compared."""

    role: str
    system: str
    request: str
    facts: JsonObject
    check: CheckInput | None
    allowed: set[float]
    cars: int


async def report_check(c: TurnContext, w: Writing, text: str) -> tuple[str, int]:
    """Text vs blocks (spec 004 FR-012): one regeneration with the violations listed; if the text still
    contradicts the blocks, the offending sentences are removed. Returns (text, sentences removed). Raises what
    the regeneration raises except a provider failure (see the module docstring)."""
    if w.check is None:
        return text, 0
    bad = report_violations(text, w.check)
    if not bad:
        return text, 0
    await c.status("composing", f"Correcting {len(bad)} sentence(s) that contradict the data")
    try:
        again = await c.ports.llm.text(
            w.role,
            w.system + "\nYou have no tools; use only the JSON facts provided.",
            w.request + "\n\n" + violations_prompt(bad) + "\n\nPrevious text:\n" + text
            + "\n\nValidated facts JSON:\n" + json.dumps(w.facts, ensure_ascii=False, default=str),
        )  # fmt: skip
    except Exception as e:
        if not (isinstance(e, ProviderUnavailable) or classify(e) in TRANSIENT):
            raise
        log.warning("guard.rewrite_failed chat_id=%s turn_id=%s %s", c.chat_id, c.turn_id, classify(e))
        return drop_sentences(text, bad), len(bad)
    again, dropped = check_numbers(again, w.allowed, w.cars)
    still = report_violations(again, w.check)
    return (drop_sentences(again, still), dropped + len(still)) if still else (again, dropped)


def critique_lead(inp: ComposeIn, lang: str | None) -> str:
    """What was done about the critique, by code (never only an apology)."""
    areas = sorted({str(r.get("area")) for r in inp.research_results if r.get("area")})
    if inp.research_done and areas:
        return t("critique_researched", lang, areas=", ".join(areas))
    what = " ".join(str(inp.user_text or "").split())[:80]
    return t("critique_reworked", lang, what=what)
