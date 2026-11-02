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

from langgraph.runtime import Runtime

from automind.application import compose
from automind.domain.casefile import CaseFile, Shown
from automind.domain.policy import fingerprint
from automind.orchestration import agents
from automind.orchestration.guard import check_numbers, numbers_in, removal_notice
from automind.orchestration.runner import TurnContext
from automind.orchestration.state import TurnState

from .common import ctx, history, load_case, save_case
from .compute import compute


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


async def _explain(
    c: TurnContext, role: str, system: str, request: str, facts: dict[str, Any], tools: list[Any]
) -> tuple[str, list[Any]]:
    """Analyst text via scoped MCP tools when available, else from the provided facts only."""
    if tools:
        try:
            agent = c.ports.llm.agent(role, tools, system)
            res = await agent.ainvoke({"messages": [("user", request)]}, {"recursion_limit": 14})
            msgs = res["messages"]
            outputs = [m.content for m in msgs if getattr(m, "type", "") == "tool"]
            last = msgs[-1]
            return (last.text if isinstance(getattr(last, "text", None), str) else str(last.content)), outputs
        except Exception:  # noqa: BLE001 - fall back to the facts below
            pass
    text = await c.ports.llm.text(
        role,
        system + "\nYou have no tools; use only the JSON facts provided.",
        request + "\n\nValidated facts JSON:\n" + json.dumps(facts, ensure_ascii=False, default=str),
    )
    return text, []


def make_report_node(tools: list[Any]):  # noqa: ANN201
    async def report_node(state: TurnState, runtime: Runtime[TurnContext]) -> dict[str, Any]:
        c = ctx(runtime)
        _, case = await load_case(c)
        await c.status("computing", "Computing criteria scores, metrics and the drag race")
        comp = await compute(c, case, list(state.get("notices", [])))
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
        car_list = [{"car_id": x["variant"].id, "label": x["variant"].label} for x in comp.cars]
        request = (
            f"User message: {state.get('user_text', '')}\nchat_id (for get_case/score_criteria): {c.chat_id}\n"
            f"Cars (car_ids for tools): {json.dumps(car_list)}"
        )
        text, outputs = await _explain(c, "reporter", system, request, comp.facts, agents.scoped_tools(tools, name))
        allowed = (
            numbers_in(comp.facts) | numbers_in(comp.blocks) | numbers_in(outputs) | numbers_in(_case_summary(case))
        )
        text, dropped = check_numbers(text, allowed)
        blocks = comp.blocks + ([removal_notice(dropped)] if dropped else [])
        fp = fingerprint(case)
        case.shown.append(
            Shown(
                turn_seq=len(case.shown) + 1, fingerprint=fp, blocks=[b["type"] for b in blocks], persona=case.persona
            )
        )
        case.asked = []  # a useful answer was given: a later new ambiguity may be asked about again
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
    comp = await compute(c, case, list(state.get("notices", [])))
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
    if dropped:
        blocks.append(removal_notice(dropped))
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
