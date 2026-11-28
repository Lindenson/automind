"""The understanding in the interpret node. S3 (spec 013 T034): the old interpreter decides the turn; the new
understanding runs beside it on the same input, concurrently (the turn waits for the slower of the two, not for
both), and the turn's `UnderstandingRecord` — with what the old one read — is logged, counted and stored. S4 (T040,
`Ports.understanding_decides`): for typed words the new understanding decides and the old interpreter runs only as
its fallback; buttons keep the S3 shadow until T046.

Off when `Ports.understanding_shadow` is false (test fakes; live: `AUTOMIND_UNDERSTANDING_SHADOW`, G8) or the prompt
`understander` is not loaded. The shadow never breaks a turn: its own failures are refused records
(`UnderstandingShadow.understand`); a bug of the shadow or a store that cannot be written (`StoreUnavailable`) is
logged at ERROR and counted in `automind_understanding_record_errors_total`. A failure of the old reading cancels
the shadow and propagates as before (the node's retry)."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

from automind.chat.application.ports import StoreUnavailable
from automind.chat.application.services.interpretation import interpret
from automind.chat.application.services.interpretation.contracts import History, Preset, Reading
from automind.chat.application.services.report.blocks.car_edit import edit_delta
from automind.chat.application.services.understanding.as_interpretation import as_interpretation
from automind.chat.application.services.understanding.shadow import ShadowTurn, UnderstandingShadow
from automind.chat.application.services.understanding.understander import Understander
from automind.chat.dialog.report_wording import WORDING
from automind.chat.dialog.turn.context import TurnContext
from automind.chat.domain.case import CaseDelta, CaseFile
from automind.chat.domain.understanding.intent import Intent
from automind.chat.domain.understanding.record import UnderstandingRecord
from automind.shared.contracts.json import JsonObject
from automind.shared.infrastructure.metrics import understanding as metrics

log = logging.getLogger(__name__)

PROMPT = "understander"
DEFAULT_WINDOW = (6, 600)  # earlier turns × characters, when `configure_history` did not run (tests)


async def read_with_shadow(c: TurnContext, case: CaseFile, history: History, text: str, preset: Preset | None,
                           old: Callable[[], Awaitable[Reading]]) -> Reading:  # fmt: skip
    """The old reading (`old()`), with the new understanding run beside it and recorded when the shadow is on;
    from S4 (`Ports.understanding_decides`) the new understanding decides typed words (`_decided`)."""
    shadow = _shadow(c)
    if shadow is None:
        return await old()
    if c.ports.understanding_decides and preset is None:
        return await _decided(c, shadow, ShadowTurn(c.chat_id, c.turn_id, case, history, text, None), old)
    turn = ShadowTurn(c.chat_id, c.turn_id, case, history, text, dict(preset) if preset else None)
    task = asyncio.create_task(shadow.understand(turn))
    started = time.monotonic()
    try:
        reading = await old()
    except BaseException:
        task.cancel()
        raise
    if preset is None and not reading.picked:
        metrics.seconds("old", time.monotonic() - started)
    try:
        rec = (await task).model_copy(update={"old_reading": _old(reading)})
    except Exception:  # noqa: BLE001 - a bug in the shadow must not break the turn the old reading decides
        log.exception("understanding.shadow_failed chat_id=%s turn_id=%s", c.chat_id, c.turn_id)
        metrics.record_error()
        return reading
    await _keep(shadow, rec, c)
    return reading


async def _decided(c: TurnContext, shadow: UnderstandingShadow, turn: ShadowTurn,
                   old: Callable[[], Awaitable[Reading]]) -> Reading:  # fmt: skip
    """Spec 013 S4 (T040): typed words read by the new understanding, its intent applied as the interpretation; the
    old interpreter runs only when the understanding refused (model down, output not valid) — the record keeps both
    then. A bug of the understanding is logged, counted and falls back to the old reading too."""
    try:
        rec, understood = await shadow.understand_words(turn)
    except Exception:  # noqa: BLE001 - a bug in the new chain must not lose the turn: the old reading decides
        log.exception("understanding.decide_failed chat_id=%s turn_id=%s", c.chat_id, c.turn_id)
        metrics.record_error()
        return await old()
    if rec.intent is None or understood is None:
        reading = await old()
        await _keep(shadow, rec.model_copy(update={"old_reading": _old(reading)}), c)
        return reading
    i = as_interpretation(Intent.model_validate(rec.intent), understood)
    await _keep(shadow, rec, c)
    return Reading(i, i.language)


def _shadow(c: TurnContext) -> UnderstandingShadow | None:
    prompt = c.ports.ref.prompts.get(PROMPT)
    if not c.ports.understanding_shadow or not prompt:
        return None
    match_make = c.ports.ref.makes.match_make if c.ports.ref.makes is not None else None

    def edit(case: CaseFile, key: str, field: str, value: str) -> CaseDelta:
        return edit_delta(case, key, field, value, match_make)

    understander = Understander(c.ports.llm, prompt, interpret.HISTORY_WINDOW or DEFAULT_WINDOW)
    return UnderstandingShadow(understander, WORDING, c.ports.ref.makes, c.ports.understanding, edit)


def _old(reading: Reading) -> JsonObject:
    i = reading.interpretation
    return {"interpretation": i.model_dump(mode="json") if i else None, "language": reading.language,
            "picked": reading.picked, "ask": reading.ask}  # fmt: skip


async def _keep(shadow: UnderstandingShadow, rec: UnderstandingRecord, c: TurnContext) -> None:
    """Log, count and store the turn's understanding (see the module docstring)."""
    rules = [o.rule for o in rec.overrides]
    log.info("understanding.shadow chat_id=%s turn_id=%s source=%s refused=%s overrides=%s dropped=%s repeated=%s",
             c.chat_id, c.turn_id, rec.source, rec.refused, rules, [d.check for d in rec.rejected],
             rec.question_repeated)  # fmt: skip
    metrics.understood(rec.source, refused=rec.refused is not None, overrides=rules,
                       dropped=[d.check for d in rec.rejected], repeated=rec.question_repeated)  # fmt: skip
    if rec.latency_ms is not None:
        metrics.seconds("new", rec.latency_ms / 1000)
    try:
        await shadow.record(rec)
    except StoreUnavailable:
        log.exception("understanding.record_failed chat_id=%s turn_id=%s", c.chat_id, c.turn_id)
        metrics.record_error()
