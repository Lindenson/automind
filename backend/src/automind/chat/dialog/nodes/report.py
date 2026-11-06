"""REPORT, ANSWER_FROM_CONTEXT and ANSWER_GENERAL nodes.

Numbers come only from code (the report service); the writer explains and every number it writes is checked by
the guard (FR-031). A report records its fingerprint so an unchanged case is never re-reported (FR-004).
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from automind.chat.application.services.report.computations import persist_computations
from automind.chat.application.services.report.contracts import Computed
from automind.chat.application.services.report.service import ReportService
from automind.chat.dialog.context import ctx, history, load_case, record_intake, save_case
from automind.chat.dialog.report_followup import shown_answer, shown_report
from automind.chat.dialog.report_wording import WORDING
from automind.chat.dialog.report_writer import log_removed, write_answer, write_report
from automind.chat.dialog.runner import TurnContext
from automind.chat.dialog.state import TurnState
from automind.chat.domain.case import CaseFile


def make_report_node():  # noqa: ANN201
    async def report_node(state: TurnState, runtime: Runtime[TurnContext]) -> dict[str, Any]:
        c = ctx(runtime)
        _, case = await load_case(c)
        await c.status("computing", "Computing criteria scores, metrics and the drag race")
        lang = state.get("language", "en")
        comp = await compute(c, case, list(state.get("notices", [])), lang)
        await persist(c, case, comp, mileage={x.variant_id: x.mileage_km for x in case.cars if x.variant_id},
                      rates=case.rates_override.model_dump(exclude_none=True))  # fmt: skip
        await c.status("composing", "Writing the conclusion for you")
        text = await write_report(c, state, case, comp)
        blocks, fp = shown_report(case, comp, lang, (c.ports.ref.profile_defaults or {}).get("probe"))
        version = await save_case(c, case, [], publish=False)
        await c.status("done", "Done")
        # a rescore is a report too: its fingerprint is what the next "nothing new" is compared against
        return {"reply_text": text, "blocks": blocks, "action": "REPORT", "fingerprint": fp, "case_version": version}

    return report_node


async def answer_node(state: TurnState, runtime: Runtime[TurnContext]) -> dict[str, Any]:
    """ANSWER_FROM_CONTEXT: recompute from cached data, no research (FR-004, FR-029). A weights change shows the
    recomputed criteria scores; "nothing new" sends no blocks."""
    c = ctx(runtime)
    _, case = await load_case(c)
    nothing_new = bool(state["decision"].get("nothing_new"))
    comp = await compute(c, case, list(state.get("notices", [])), state.get("language", "en"))
    if state.get("case_changed") and case.race_settings is not None:  # a new race: keep it reproducible
        await persist(c, case, comp, mileage={}, rates={}, estimates=False)
    text, dropped = await write_answer(c, state, case, comp, nothing_new)
    blocks, remembered = shown_answer(state, case, comp, nothing_new)
    if remembered:
        await save_case(c, case, [], publish=False)
    log_removed(c, "answer", dropped)
    await c.status("done", "Done")
    return {"reply_text": text, "blocks": blocks, "action": "ANSWER_FROM_CONTEXT"}


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


async def compute(c: TurnContext, case: CaseFile, notices: list[dict[str, Any]], lang: str = "en") -> Computed:
    """The report's numbers and blocks for this turn (the report service, in the person's language)."""

    async def intake_log(kind: str, **details: object) -> None:
        await record_intake(c, kind, **details)

    return await ReportService(c.ports, WORDING, intake_log).run(case, notices, lang)


async def persist(c: TurnContext, case: CaseFile, comp: Computed, *, mileage: dict[str, int | None],
                  rates: dict[str, Any], estimates: bool = True) -> None:  # fmt: skip
    """The turn's ownership-cost estimates (unless `estimates` is False) and race, kept with their inputs."""
    await persist_computations(c.ports.computations, c.turn_id, comp.tco if estimates else [], comp.cars, comp.race,
                               rates, case.prediction.model_dump() if case.prediction else None, mileage)  # fmt: skip
