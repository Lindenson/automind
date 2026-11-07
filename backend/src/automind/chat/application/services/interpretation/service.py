"""The interpretation service (spec 012 S9c): one message of the person, read and applied to the case.

`read` turns the message into an `Interpretation` — from a button (a preset or a car edit, no model call), from a
tapped option (code), or from the model (`interpret`, checked by code). `apply` applies it to the case through named
pure stages: the delta, the make to choose from, the condition inherited, the persona's words and defaults, the
request settled, the safety net for named cars, the person's facts and figures from their words, and the pending
question answered or not.

Failures: a model answer that cannot be read, or names a car the case does not have, is not an error of the turn —
`Reading.ask` is "rephrase"; a car edit or a delta for a car the case does not have gives `ask` "which_car" and
nothing is applied. An LLM transport failure propagates (the turn fails and is retried from its checkpoint). The
intake log never fails the turn. The service writes nothing else: the caller saves the case it returns."""

from __future__ import annotations

from dataclasses import dataclass

from automind.chat.application.ports import IntakeLog
from automind.chat.application.services.interpretation.contracts import (
    Applied,
    History,
    Interpretation,
    InterpretError,
    Preset,
    Reading,
    ReplyWords,
)
from automind.chat.application.services.interpretation.interpret import interpret
from automind.chat.application.services.interpretation.stages.brand_explained import brand_from_text
from automind.chat.application.services.interpretation.stages.cars_safety_net import cars_safety_net
from automind.chat.application.services.interpretation.stages.make_to_choose import make_to_choose_from
from automind.chat.application.services.interpretation.stages.person_facts import person_from_text
from automind.chat.application.services.interpretation.stages.picked_option import picked_option
from automind.chat.application.services.interpretation.stages.stated_energy import energy_from_text
from automind.chat.application.services.interpretation.stages.understood import not_understood, pending_answered
from automind.chat.application.services.report.blocks.car_view import edit_delta
from automind.chat.domain import intake
from automind.chat.domain.case import CaseFile, apply, apply_defaults
from automind.shared.contracts.config import Reference
from automind.shared.contracts.llm import LLM

_INTAKE_PENDING = ("QUESTIONS", "CONFIRM_VARIANTS", "CONFIRM_INTAKE")  # pending kinds every reply answers
_NO_SAFETY_NET = ("confirm_yes", "confirm_no", "rescore")  # requests that never add cars from the words
PERSONA_WORDS_CHARS = 120  # the person's words kept as the evidence of a persona


@dataclass(frozen=True)
class ApplyRequest:
    """A read message to apply: `text` is the person's words ("" for a car edit, whose label is not their words);
    `picked` says the words are one of the offered options (`Reading.picked`)."""

    case: CaseFile
    interpretation: Interpretation
    text: str
    picked: bool
    year: int


class InterpretationService:
    """Reads one message and applies it to the case, with the model, the reference data and the dialog's words."""

    def __init__(self, llm: LLM, ref: Reference, words: ReplyWords, log: IntakeLog) -> None:
        self.llm, self.ref, self.words, self.log = llm, ref, words, log

    async def read(self, case: CaseFile, history: History, text: str, preset: Preset | None) -> Reading:
        """The message read into an interpretation, or the question to ask back (see the module docstring).
        `history` is the last turns before this message; a car edit is recorded in the intake log."""
        said = [m["text"] for m in history if m["role"] == "user"]
        if preset and preset.get("kind") == "car_edit":  # spec 010 FR-037: a structured car edit, applied by code
            return await self._car_edit(case, said, preset)
        if preset:  # a button already knows the request ("find it"): no model call
            return _reading(Interpretation.model_validate({
                "request": preset.get("kind", "research_more"),
                "language": preset.get("language") or self.words.guess_language(said),
                "focus_cars": list(preset.get("focus_cars") or []), "focus_areas": list(preset.get("areas") or []),
            }))  # fmt: skip
        if picked_option(case, text, self.words) is not None:  # a tapped option: answered by code (spec 007 F)
            i = Interpretation(request="compare", language=self.words.guess_language(said))
            return Reading(i, i.language, picked=True)
        try:
            i = await interpret(self.llm, self.ref.prompts["interpreter"], case, history, text)
        except InterpretError:
            return Reading(None, None, ask="rephrase")
        earlier = said[:-1] if said and said[-1] == text else said
        lang = self.words.stable_language(i.language, text, earlier)
        return _reading(i if lang is None or lang == i.language else i.model_copy(update={"language": lang}))

    def apply(self, req: ApplyRequest) -> Applied:
        """The case after the message, through the stages in order (see the module docstring). Pure: the caller
        saves `Applied.case` when `Applied.saved`."""
        before, i, text = req.case, req.interpretation, req.text
        try:
            new, changes = self._delta_applied(req)
        except ValueError:  # the delta names a car the case does not have
            return Applied(before, i.request, ask="which_car")
        changes += make_to_choose_from(new, before, text, self.ref.makes)
        changes += intake.inherit_condition(before, new)
        _keep_persona_words(new, i)
        new = apply_defaults(new, self.ref.profile_defaults)  # spec 007 FR-003: what is assumed is marked ASSUMED
        request: str = "choose_for_me" if self.words.choose_for_me(text) else i.request
        if _intake_pending(before) and request in ("general_question", "chitchat"):
            request = "compare"  # spec 005 FR-022: while an intake step is pending, every reply is an intake answer
            changes += brand_from_text(new, before, text, self.ref.makes)
        if not new.cars and new.pending is None and request not in _NO_SAFETY_NET:
            new, request, found = cars_safety_net(new, text, self.ref.makes, req.year, request)
            changes += found
        changes += person_from_text(new, before, text, self.ref.regions)
        changes += energy_from_text(new, text, self.ref.makes)
        unclear = not_understood(before, new, request)
        new, answered = pending_answered(new, request)
        changes += answered
        return Applied(new, request, changes, unclear, saved=bool(changes) or new != before)

    def _delta_applied(self, req: ApplyRequest) -> tuple[CaseFile, list[str]]:
        """The offered option the words pick, else the interpretation's delta. Raises ValueError for an unknown car."""
        picked = picked_option(req.case, req.text, self.words) if req.picked else None
        return picked if picked is not None else apply(req.case, req.interpretation.delta, current_year=req.year)

    async def _car_edit(self, case: CaseFile, said: list[str], preset: Preset) -> Reading:
        """ "Change" on a car (engine, gearbox, trim, generation, not this car, remove): the delta is built by code and
        goes the normal way (apply → identify → assess → policy); the model is never called."""
        lang = preset.get("language") or self.words.guess_language(said)
        key, field = str(preset.get("car_key") or ""), str(preset.get("field") or "")
        match_make = self.ref.makes.match_make if self.ref.makes is not None else None
        try:
            delta = edit_delta(case, key, field, str(preset.get("value") or ""), match_make)
        except (ValueError, KeyError):
            return Reading(None, lang, ask="which_car")
        await self.log("CARD_EDITED", key, field, source="car_edit")
        return _reading(Interpretation(request="correction", language=lang, relation="correction", delta=delta))


def _reading(i: Interpretation) -> Reading:
    return Reading(i, i.language)


def _intake_pending(case: CaseFile) -> bool:
    return case.pending is not None and case.pending.kind in _INTAKE_PENDING


def _keep_persona_words(new: CaseFile, i: Interpretation) -> None:
    """The words the persona came from, kept as its evidence (in place)."""
    sp = i.delta.set_persona
    if sp is not None and i.persona_evidence and new.persona == sp.persona:
        new.profile.evidence["persona"] = i.persona_evidence.strip()[:PERSONA_WORDS_CHARS]
