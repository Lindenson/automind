"""Spec 013 T005: one golden case through today's understanding path, as the graph runs it on a typed message.

The path per open question (verified in `dialog/nodes`, 2026-11-27):
- QUESTIONS, CONFIRM_VARIANTS: the pending stays on the case; the message goes to the interpreter.
- CONFIRM_INTAKE, CONFIRM_COST: `apply_intake` / `apply_cost` clear the pending, then the interpreter reads the text.
- LIMIT: `phrases.yes_or_no` first ("да" → continue, "нет" → stop); anything else → the interpreter, no pending.
Then `InterpretationService.apply` and the policy's `decide`. Two steps of the graph are not run: `identify` and
`assess` need the catalogue, which fixtures do not carry; car facts come from the fixture's resolution instead
(`_car_facts`). The action is therefore the policy's answer to the fixture's state, not a full turn.

The old labels are mapped to the new fields by understanding-spec §4 "Соответствие старых меток" (`observed`).
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from decimal import Decimal

from automind.chat.application.services.interpretation.contracts import Interpretation, Reading
from automind.chat.application.services.interpretation.service import ApplyRequest, InterpretationService
from automind.chat.dialog.phrases import yes_or_no
from automind.chat.dialog.policy import CarFacts, Situation, decide
from automind.chat.domain.case import CaseFile
from automind.chat.domain.case.car import CaseCar, Constraints
from automind.chat.domain.case.casefile import Pending, Shown
from automind.chat.domain.decision import PolicyConfig, RequestKind
from tests.eval.understanding.fixture_models import CarFixture, CaseFixture, PendingFixture
from tests.eval.understanding.schema import Case
from tests.eval.understanding.vocab import AnswerKind, GoalKind, PendingKind

YEAR = 2026
_KEEPS_PENDING = (PendingKind.QUESTIONS, PendingKind.CONFIRM_VARIANTS)
_GOAL_OF_REQUEST: dict[str, GoalKind] = {
    "compare": GoalKind.COMPARE, "single": GoalKind.SINGLE, "follow_up_question": GoalKind.FOLLOW_UP,
    "weights_change": GoalKind.CHANGE_PRIORITIES, "research_more": GoalKind.RESEARCH_MORE,
    "general_question": GoalKind.ASK_GENERAL, "critique": GoalKind.CRITIQUE,
}  # fmt: skip
_ANSWER_OF_REQUEST: dict[str, AnswerKind] = {
    "confirm_yes": AnswerKind.YES, "confirm_no": AnswerKind.NO, "choose_for_me": AnswerKind.CHOOSE_FOR_ME,
}  # fmt: skip
_REACTION_OF_RELATION = {"rephrase": "rephrase", "correction": "correction", "complaint": "complaint",
                         "thanks": "thanks"}  # fmt: skip
_EUR = re.compile(r"€\s?(\d+(?:[.,]\d+)?)")


@dataclass(frozen=True)
class Observed:
    """What today's path made of one message, in the new fields (understanding-spec §4)."""

    language: str | None
    request: str | None
    answer: AnswerKind | None
    option_id: str | None
    goals: tuple[GoalKind, ...]
    reaction: str | None
    rejections: tuple[tuple[str, str], ...]  # (car key, level)
    replaced_keys: tuple[str, ...]  # cars the delta replaces (`replace_cars`, a correction)
    before: CaseFile
    after: CaseFile
    delta_empty: bool
    action: str
    latency_ms: float  # the understanding step (read), wall clock; 0 when no model call was made
    model_called: bool
    notes: list[str] = field(default_factory=list)


def case_of(fx: CaseFixture, pending: PendingFixture | None) -> CaseFile:
    """The case file of a fixture, with the pending the interpreter sees on today's path (see the module doc)."""
    case = CaseFile(cars=[_car(c) for c in fx.cars], next_car_no=len(fx.cars) + 1)
    if fx.report_shown:
        case.shown = [Shown(turn_seq=1, fingerprint="eval-report")]
    if pending is not None and pending.kind in _KEEPS_PENDING:
        case.pending = _old_pending(pending)
    return case


def _car(c: CarFixture) -> CaseCar:
    named = " ".join(x for x in (c.make, c.model) if x)
    shown = c.resolution in ("PROPOSED", "CONFIRMED", "AUTO_OK") and c.label
    return CaseCar(key=c.key, request_text=c.request_text or named or c.key, make=c.make, model=c.model,
                   condition=c.condition, year=c.year, resolution=c.resolution, label=c.label,
                   variant_id=f"eval-{c.key}" if shown else None, replaced=c.replaced,
                   constraints=Constraints(fuel_hint=c.fuel))  # fmt: skip


def _old_pending(p: PendingFixture) -> Pending:
    if p.kind is PendingKind.QUESTIONS:
        return Pending(kind="QUESTIONS", items=[{"kind": i.topic, "car": i.car, "text": p.question} for i in p.items])
    items: list[dict[str, object]] = [
        {"car": i.car, "options": [{"id": o.id, "label": o.label, "car": i.car} for o in i.options]} for i in p.items
    ]
    return Pending(kind="CONFIRM_VARIANTS", items=items)


def history_of(case: Case, pending: PendingFixture | None) -> list[dict[str, str]]:
    """The bot's last message as the interpreter's history: the case's summary, else the open question."""
    said = case.history or (pending.question if pending else None)
    return [{"role": "assistant", "text": said}] if said else []


async def run_case(service: InterpretationService, case: Case, fx: CaseFixture, pending: PendingFixture | None,
                   cfg: PolicyConfig) -> Observed:  # fmt: skip
    """One case through today's path (module doc). Raises what the model gateway raises (provider down, budget)."""
    before = case_of(fx, pending)
    lang = fx.chat_language.value if fx.chat_language else None
    if pending is not None and pending.kind is PendingKind.LIMIT and (typed := yes_or_no(case.message)):
        return _limit_answer(before, typed, lang)
    if pending is not None and pending.kind in _KEEPS_PENDING and (option := _option_by_label(pending, case.message)):
        return _tapped(before, option, lang, fx, pending, cfg)
    started = time.monotonic()
    reading = await service.read(before, history_of(case, pending), case.message, None)
    latency = (time.monotonic() - started) * 1000
    if reading.interpretation is None:
        return _asked_back(before, reading, latency)
    applied = service.apply(ApplyRequest(before, reading.interpretation, case.message, reading.picked, YEAR))
    if applied.ask is not None:
        return _asked_back(before, reading, latency)
    action = decide(_situation(applied.case, applied.request, fx, pending, applied.changes), cfg).action.kind
    return _observed(reading, before, applied.case, applied.request, pending, case.message, action, latency)


def _limit_answer(case: CaseFile, typed: str, lang: str | None) -> Observed:
    """`apply_limit`: a plain yes continues the research, a plain no answers with what was collected (the reply
    keeps the chat's language)."""
    yes = typed == "yes"
    return Observed(language=lang, request=None, answer=AnswerKind.YES if yes else AnswerKind.NO, option_id=None,
                    goals=(), reaction=None, rejections=(), replaced_keys=(), before=case, after=case,
                    delta_empty=True, action="RESEARCH" if yes else "REPORT", latency_ms=0.0, model_called=False,
                    notes=["limit: phrases.yes_or_no"])  # fmt: skip


def _tapped(case: CaseFile, option: str, lang: str | None, fx: CaseFixture, pending: PendingFixture,
            cfg: PolicyConfig) -> Observed:  # fmt: skip
    """The words are an offered option's label: today `picked_option` answers by code, no model call (the
    fixture's labels stand in for the options the case would carry)."""
    action = decide(_situation(case, "compare", fx, pending, []), cfg).action.kind
    return Observed(language=lang, request="compare", answer=AnswerKind.OPTION, option_id=option, goals=(),
                    reaction=None, rejections=(), replaced_keys=(), before=case, after=case, delta_empty=True,
                    action=action, latency_ms=0.0, model_called=False, notes=["picked by label"])  # fmt: skip


def _asked_back(case: CaseFile, reading: Reading, latency: float) -> Observed:
    """The interpreter's output was refused (or named an unknown car): the turn asks to rephrase."""
    i = reading.interpretation
    return Observed(language=reading.language, request=i.request if i else None, answer=None, option_id=None,
                    goals=(), reaction=None, rejections=(), replaced_keys=(), before=case, after=case, delta_empty=True,
                    action="ASK", latency_ms=latency, model_called=True,
                    notes=[f"asked back: {reading.ask or 'which_car'}"])  # fmt: skip


def _observed(reading: Reading, before: CaseFile, after: CaseFile, request: str, pending: PendingFixture | None,
              text: str, action: str, latency: float) -> Observed:  # fmt: skip
    i: Interpretation = reading.interpretation  # type: ignore[assignment]  # checked by the caller
    answer, option = _answer(reading, request, pending, text)
    goal = _GOAL_OF_REQUEST.get(request)
    if goal is GoalKind.COMPARE and answer is not None and len(after.cars) <= len(before.cars):
        goal = None  # "compare" is also the label of a plain intake answer (spec 005 FR-022): no goal unless cars came
    reaction = "complaint" if request == "critique" else _REACTION_OF_RELATION.get(i.relation)
    return Observed(
        language=reading.language or i.language, request=request, answer=answer, option_id=option,
        goals=(goal,) if goal else (), reaction=reaction,
        rejections=tuple((r.target_key, str(r.level)) for r in i.delta.rejections),
        replaced_keys=tuple(r.target_key for r in i.delta.replace_cars), before=before, after=after,
        delta_empty=i.delta.is_empty(), action=action, latency_ms=latency, model_called=not reading.picked,
    )  # fmt: skip


def _answer(reading: Reading, request: str, pending: PendingFixture | None,
            text: str) -> tuple[AnswerKind | None, str | None]:  # fmt: skip
    """Today's answer to the open question. QUESTIONS: every reply is an answer (spec 005 FR-022, `apply` turns
    general/chitchat into compare); a tapped option by its label. Confirmations: confirm_yes/no, choose_for_me."""
    if pending is None:
        return None, None
    if reading.picked:
        return AnswerKind.OPTION, _option_by_label(pending, text)
    if request in _ANSWER_OF_REQUEST:
        return _ANSWER_OF_REQUEST[request], None
    if pending.kind is PendingKind.QUESTIONS:
        return AnswerKind.VALUE, None
    return None, None


def _option_by_label(p: PendingFixture, text: str) -> str | None:
    said = text.strip().casefold()
    return next((o.id for i in p.items for o in i.options if o.label.casefold() == said), None)


def _situation(case: CaseFile, request: RequestKind, fx: CaseFixture, pending: PendingFixture | None,
               changes: list[str]) -> Situation:  # fmt: skip
    """The policy's input from the fixture: no catalogue, so the facts come from each car's resolution."""
    known = {c.key: c for c in fx.cars}
    cost = _EUR.search(pending.question) if pending and pending.kind is PendingKind.CONFIRM_COST else None
    return Situation(
        case=case, request=request, cars=tuple(_car_facts(c, known.get(c.key), fx.report_shown) for c in case.cars),
        cost_estimate_eur=Decimal(cost.group(1).replace(",", ".")) if cost else None,
        last_fingerprint="eval-report" if fx.report_shown else None, cost_approved=False, research_declined=False,
        case_changed=bool(changes), feasibility_pending=False, pass_no=1,
    )  # fmt: skip


def _car_facts(car: CaseCar, fx: CarFixture | None, report_shown: bool) -> CarFacts:
    identified = car.resolution in ("PROPOSED", "CONFIRMED", "AUTO_OK")
    unchanged = fx is not None and (fx.make, fx.model) == (car.make, car.model)
    return CarFacts(key=car.key, identity_known=bool(car.make and car.model), in_catalog=identified,
                    ambiguous=False, plausible_generations=1 if identified else 0,
                    data_fresh=report_shown and unchanged, gearbox_mixed=False)  # fmt: skip
