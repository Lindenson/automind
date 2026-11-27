"""REPORT, ANSWER_FROM_CONTEXT and ANSWER_GENERAL nodes.

Numbers come only from code (the report service); the writer explains and every number it writes is checked by
the guard (FR-031). A report records its fingerprint so an unchanged case is never re-reported (FR-004).
"""

from __future__ import annotations

from typing import Any

from automind.chat.application.services.report.blocks.notice import Notice
from automind.chat.application.services.report.computations import persist_computations
from automind.chat.application.services.report.contracts import Computed
from automind.chat.application.services.report.service import ReportService
from automind.chat.dialog.context import history, load_case, record_intake, save_case
from automind.chat.dialog.contract import Retry, node
from automind.chat.dialog.nodes.report_io import AnswerIn, ComposeIn, GeneralIn, ReplyOut, ReportOut
from automind.chat.dialog.report_followup import shown_answer, shown_report
from automind.chat.dialog.report_wording import WORDING
from automind.chat.dialog.report_writer import log_removed, write_answer, write_report
from automind.chat.dialog.turn.context import TurnContext
from automind.chat.domain.case import CaseFile


@node("report", reads=ComposeIn, writes=ReportOut, retry=Retry.PROVIDER)
async def report_node(inp: ComposeIn, c: TurnContext) -> ReportOut:
    """REPORT (and RESCORE): the numbers by code, the text by the reporter, its fingerprint remembered (FR-004)."""
    _, case = await load_case(c)
    await c.status("computing", "Computing criteria scores, metrics and the drag race")
    lang = inp.language
    comp = await compute(c, case, list(inp.notices), lang)
    await persist(c, case, comp, mileage={x.variant_id: x.mileage_km for x in case.cars if x.variant_id},
                  rates=case.rates_override.model_dump(exclude_none=True))  # fmt: skip
    await c.status("composing", "Writing the conclusion for you")
    text = await write_report(c, inp, case, comp)
    blocks, fp = shown_report(case, comp, lang, (c.ports.ref.profile_defaults or {}).get("probe"))
    version = await save_case(c, case, [], publish=False)
    await c.status("done", "Done")
    # a rescore is a report too: its fingerprint is what the next "nothing new" is compared against
    return ReportOut(reply_text=text, blocks=blocks, action="REPORT", fingerprint=fp, case_version=version)


@node("answer", reads=AnswerIn, writes=ReplyOut, retry=Retry.PROVIDER)
async def answer_node(inp: AnswerIn, c: TurnContext) -> ReplyOut:
    """ANSWER_FROM_CONTEXT: recompute from cached data, no research (FR-004, FR-029). A weights change shows the
    recomputed criteria scores; "nothing new" sends no blocks."""
    _, case = await load_case(c)
    nothing_new = bool(inp.decision.get("nothing_new"))
    comp = await compute(c, case, list(inp.notices), inp.language)
    if inp.case_changed and case.race_settings is not None:  # a new race: keep it reproducible
        await persist(c, case, comp, mileage={}, rates={}, estimates=False)
    text, dropped = await write_answer(c, inp, case, comp, nothing_new)
    blocks, remembered = shown_answer(inp, case, comp, nothing_new)
    if remembered:
        await save_case(c, case, [], publish=False)
    log_removed(c, "answer", dropped)
    await c.status("done", "Done")
    return ReplyOut(reply_text=text, blocks=blocks, action="ANSWER_FROM_CONTEXT")


@node("general", reads=GeneralIn, writes=ReplyOut, retry=Retry.PROVIDER)
async def general_node(inp: GeneralIn, c: TurnContext) -> ReplyOut:
    """ANSWER_GENERAL: a general question answered by the model from the last messages."""
    await c.status("composing", "Answering")
    hist = "\n".join(f"{m['role']}: {m['text'][:300]}" for m in (await history(c))[-4:])
    text = await c.ports.llm.text(
        "general",
        c.ports.ref.prompts["general"].format(language=inp.language),
        f"{hist}\nuser: {inp.user_text}",
    )
    await c.status("done", "Done")
    return ReplyOut(reply_text=text, blocks=[], action="ANSWER_GENERAL")


async def compute(c: TurnContext, case: CaseFile, notices: list[Notice], lang: str = "en") -> Computed:
    """The report's numbers and blocks for this turn (the report service, in the person's language)."""

    async def intake_log(kind: str, **details: object) -> None:
        await record_intake(c, kind, None, None, **details)

    return await ReportService(c.ports, WORDING, intake_log).run(case, notices, lang)


async def persist(c: TurnContext, case: CaseFile, comp: Computed, *, mileage: dict[str, int | None],
                  rates: dict[str, Any], estimates: bool = True) -> None:  # fmt: skip
    """The turn's ownership-cost estimates (unless `estimates` is False) and race, kept with their inputs."""
    await persist_computations(c.ports.computations, c.turn_id, comp.tco if estimates else [], comp.cars, comp.race,
                               rates, case.prediction.model_dump() if case.prediction else None, mileage)  # fmt: skip
