"""The understanding in the shadow (spec 013 S3, T034): the new chain — Understander → validate_understanding →
IntentResolver — run on the turn's input beside the old interpreter, which still decides. Its result is one
`UnderstandingRecord` per turn, so the two can be compared on real traffic before S4 switches.

`understand` never raises: a refused reading, a model that fails or a spent budget become a record with `refused`
(the shadow must not break a turn). `record` writes through the `UnderstandingLog` and raises `StoreUnavailable`
(the caller logs and counts it). Reading the chat's previous question (for "asked again") tolerates a store down."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from automind.chat.application.ports import StoreUnavailable, UnderstandingLog
from automind.chat.application.services.understanding.resolver import IntentResolver, system_intent
from automind.chat.application.services.understanding.rules import Context, LanguageWords
from automind.chat.application.services.understanding.understander import History, Message, Understander
from automind.chat.application.services.understanding.validate import validate_understanding
from automind.chat.domain.case import CaseDelta, CaseFile
from automind.chat.domain.turn import PresetKind, Role, preset_kind
from automind.chat.domain.understanding.intent import Intent, IntentSource, UiAction, UiActionKind, Understanding
from automind.chat.domain.understanding.open_question import OpenQuestion, open_question
from automind.chat.domain.understanding.record import UnderstandingRecord
from automind.shared.contracts.config import MakeNames
from automind.shared.contracts.json import JsonObject

log = logging.getLogger(__name__)

CarEdit = Callable[[CaseFile, str, str, str], CaseDelta]  # (case, car key, field, value) → delta; ValueError/KeyError
_UI = {PresetKind.PICK: UiActionKind.PICK_OPTION, PresetKind.RESEARCH_MORE: UiActionKind.RESEARCH_MORE,
       PresetKind.CAR_EDIT: UiActionKind.EDIT_CAR, PresetKind.RESCORE: UiActionKind.PANEL_EDIT}  # fmt: skip


@dataclass(frozen=True)
class ShadowTurn:
    """One turn's input: the case before it, the last turns, and the words or the button."""

    chat_id: str
    turn_id: str
    case: CaseFile
    history: History
    text: str
    preset: Mapping[str, object] | None


class UnderstandingShadow:
    """Runs the new understanding for a turn and records it."""

    def __init__(self, understander: Understander, words: LanguageWords, makes: MakeNames | None,
                 log_: UnderstandingLog | None, edit: CarEdit) -> None:  # fmt: skip
        self.understander, self.words, self.makes, self.log, self.edit = understander, words, makes, log_, edit
        self.resolver = IntentResolver()

    async def understand(self, t: ShadowTurn) -> UnderstandingRecord:
        """The turn's understanding as a record (see the module docstring); `old_reading` is left for the caller."""
        return (await self.understand_words(t))[0]

    async def understand_words(self, t: ShadowTurn) -> tuple[UnderstandingRecord, Understanding | None]:
        """The record, and for typed words that were understood the checked `Understanding` the record's intent
        was resolved from (spec 013 S4: the turn applies it); None for a button, the system or a refusal."""
        question = open_question(t.case.pending)
        base: JsonObject = {"chat_id": t.chat_id, "turn_id": t.turn_id,
                            "open_question_id": question.id if question else None,
                            "question_repeated": await self._repeated(t.chat_id, question)}  # fmt: skip
        earlier = [m["text"] for m in t.history if m.get("role") == Role.USER]
        ctx = Context(t.case, question, t.text, earlier, self.words, self.makes)
        kind = preset_kind(t.preset)
        if kind is PresetKind.REPORT_SAVED:
            language = _str((t.preset or {}).get("language")) or self.words.guess_language(earlier)
            return _record(base, {"system": "report_saved"}, question, system_intent(language)), None
        if kind is not None:
            return self._button(base, kind, t, ctx), None
        return await self._words(base, t, ctx)

    async def record(self, rec: UnderstandingRecord) -> None:
        """Store `rec` (nothing without a log). Raises `StoreUnavailable`."""
        if self.log is not None:
            await self.log.record(rec)

    async def _words(self, base: JsonObject, t: ShadowTurn,
                     ctx: Context) -> tuple[UnderstandingRecord, Understanding | None]:  # fmt: skip
        inp: JsonObject = {"text": t.text}
        try:
            reading = await self.understander.read(Message(t.case, ctx.question, t.history, t.text))
        except Exception as e:  # noqa: BLE001 - the shadow never breaks a turn: provider, budget, schema → refused
            return _record(base, inp, ctx.question, None, refused=f"{type(e).__name__}: {e}"[:300]), None
        u = reading.understanding
        call: JsonObject = {"model": reading.model, "prompt_version": reading.prompt_version,
                            "latency_ms": reading.latency_ms, "model_raw": u.model_dump(mode="json")}  # fmt: skip
        checked = validate_understanding(u, t.case, ctx.question, t.text, ctx.earlier)
        rejected = [x.model_dump() for x in checked.dropped]
        if checked.understanding is None:
            refused = _record({**base, **call, "rejected": rejected}, inp, ctx.question, None, refused=checked.refused)
            return refused, None
        intent = self.resolver.from_text(checked.understanding, ctx)
        return _record({**base, **call, "rejected": rejected}, inp, ctx.question, intent), checked.understanding

    def _button(self, base: JsonObject, kind: PresetKind, t: ShadowTurn, ctx: Context) -> UnderstandingRecord:
        p = t.preset or {}
        action = UiAction(kind=_UI[kind], option_id=_str(p.get("option_id")), car_key=_str(p.get("car_key")),
                          field=_str(p.get("field")), value=_str(p.get("value")),
                          focus_cars=_strs(p.get("focus_cars")), focus_areas=_strs(p.get("areas")))  # fmt: skip
        inp: JsonObject = {"ui": action.model_dump(mode="json")}
        changes = None
        if action.kind is UiActionKind.EDIT_CAR:
            try:
                changes = self.edit(t.case, action.car_key or "", action.field or "", action.value or "")
            except (ValueError, KeyError) as e:
                return _record(base, inp, ctx.question, None, refused=f"car edit: {e}"[:300])
        # the turn state's language is reset to "en" at the start of a turn: the person's words tell it
        language = _str(p.get("language")) or self.words.guess_language(ctx.earlier)
        return _record(base, inp, ctx.question, self.resolver.from_ui(action, ctx, language, changes))

    async def _repeated(self, chat_id: str, question: OpenQuestion | None) -> bool:
        if question is None or self.log is None:
            return False
        try:
            return await self.log.last_question(chat_id) == question.id
        except StoreUnavailable:
            log.warning("understanding.last_question_failed chat_id=%s", chat_id)
            return False


def _record(base: JsonObject, inp: JsonObject, question: OpenQuestion | None, intent: Intent | None,
            refused: str | None = None) -> UnderstandingRecord:  # fmt: skip
    source = intent.source if intent is not None else (IntentSource.UI if "ui" in inp else IntentSource.TEXT)
    full = {**inp, "question": question.model_dump(mode="json") if question else None}
    return UnderstandingRecord.model_validate({
        **base, "source": source, "input": full, "refused": refused,
        "overrides": [o.model_dump(mode="json") for o in intent.overrides] if intent else [],
        "intent": intent.model_dump(mode="json") if intent else None,
    })  # fmt: skip


def _str(v: object) -> str | None:
    return v if isinstance(v, str) and v else None


def _strs(v: object) -> list[str]:
    return [x for x in v if isinstance(x, str)] if isinstance(v, list) else []
