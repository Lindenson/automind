"""Spec 013 T034: one golden case through the new understanding chain — Understander → validate_understanding →
IntentResolver — as the S3 shadow runs it, read back into the fields the cases check (`old_path.Observed`).

Every open question is given to the model as the understanding-spec §4 shows it (id, kind, question, options with
ids), the confirmations and the research limit included: unlike the old path, nothing answers a confirmation
before the model reads the words. The action is indicative only, as in the baseline: today's policy (`decide`) on
the old request the intent maps to (S4 replaces this with the policy reading the intent); a research-limit answer
is continue → RESEARCH, stop → REPORT, as the old path. The fixture's chat language stands in for the person's
earlier words (`_LANG_SAMPLE`): the live shadow has them, the harness has only the bot's last message.
"""

from __future__ import annotations

import time

from automind.chat.application.services.understanding.resolver import IntentResolver
from automind.chat.application.services.understanding.rules import Context
from automind.chat.application.services.understanding.understander import Message, Understander
from automind.chat.application.services.understanding.validate import validate_understanding
from automind.chat.dialog import phrases
from automind.chat.dialog.policy import decide
from automind.chat.domain import intake
from automind.chat.domain.case import CaseFile, apply
from automind.chat.domain.decision import PolicyConfig, RequestKind
from automind.chat.domain.understanding.intent import AnswerKind as A
from automind.chat.domain.understanding.intent import GoalKind as G
from automind.chat.domain.understanding.intent import Intent, Reaction
from automind.chat.domain.understanding.open_question import OpenQuestion, QuestionOption
from automind.shared.contracts.config import MakeNames
from tests.eval.understanding.fixture_models import CaseFixture, PendingFixture
from tests.eval.understanding.old_path import YEAR, Observed, _situation, case_of, history_of
from tests.eval.understanding.schema import Case
from tests.eval.understanding.vocab import AnswerKind, GoalKind, PendingKind

_REQUEST_OF_ANSWER: dict[A, RequestKind] = {A.YES: "confirm_yes", A.NO: "confirm_no", A.CHOOSE_FOR_ME: "choose_for_me"}
_REQUEST_OF_GOAL: dict[G, RequestKind] = {
    G.COMPARE: "compare", G.SINGLE: "single", G.FOLLOW_UP: "follow_up_question", G.CHANGE_PRIORITIES: "weights_change",
    G.RESEARCH_MORE: "research_more", G.ASK_GENERAL: "general_question", G.CRITIQUE: "critique", G.STOP: "chitchat",
}  # fmt: skip


class _Words:
    def stable_language(self, detected: str | None, current: str, earlier: list[str]) -> str | None:
        return phrases.stable_language(detected, current, earlier)

    def guess_language(self, texts: list[str]) -> str:
        return phrases.guess_language(texts)


def question_of(p: PendingFixture) -> OpenQuestion:
    """The fixture's open question as the understanding step sees it."""
    options = tuple(QuestionOption(id=o.id, label=o.label) for item in p.items for o in item.options)
    return OpenQuestion(id=p.id, kind=p.kind.value, question=p.question, cars=tuple(sorted(p.cars())),
                        options=options)  # fmt: skip


async def run_case(understander: Understander, makes: MakeNames | None, case: Case, fx: CaseFixture,
                   pending: PendingFixture | None, cfg: PolicyConfig) -> Observed:  # fmt: skip
    """One case through the new chain (module doc). Raises what the model gateway raises (provider down, budget)."""
    before = case_of(fx, pending)
    question = question_of(pending) if pending else None
    history = history_of(case, pending)
    earlier = [m["text"] for m in history if m["role"] == "user"]
    started = time.monotonic()
    reading = await understander.read(Message(before, question, history, case.message))
    checked = validate_understanding(reading.understanding, before, question, case.message, earlier)
    latency = (time.monotonic() - started) * 1000
    if checked.understanding is None:
        return _refused(before, reading.understanding.language, latency, checked.refused or "")
    said = earlier or ([_LANG_SAMPLE[fx.chat_language.value]] if fx.chat_language else [])
    ctx = Context(before, question, case.message, said, _Words(), makes)
    intent = IntentResolver().from_text(checked.understanding, ctx)
    after, changes = _applied(before, intent)
    request = _request(intent)
    action = _action(intent, pending) or decide(_situation(after, request, fx, pending, changes), cfg).action.kind
    return _observed(intent, before, after, request, action, latency)


_LANG_SAMPLE = {"ru": "я выбираю машину", "es": "estoy eligiendo un coche", "en": "I am choosing a car"}


def _applied(before: CaseFile, i: Intent) -> tuple[CaseFile, list[str]]:
    a = i.answer_to_pending
    if a is not None and a.kind is A.OPTION and a.option_id and (picked := intake.pick_by_id(before, a.option_id)):
        before = picked[0]
    try:
        return apply(before, i.case_changes, current_year=YEAR)
    except ValueError:
        return before, []


def _request(i: Intent) -> RequestKind:
    a = i.answer_to_pending
    if a is not None and a.kind in _REQUEST_OF_ANSWER:
        return _REQUEST_OF_ANSWER[a.kind]
    if i.goals:
        return _REQUEST_OF_GOAL[i.goals[0].kind]
    if i.reaction is Reaction.COMPLAINT:
        return "critique"
    if i.reaction is Reaction.CORRECTION:
        return "correction"
    return "compare" if a is not None or not i.case_changes.is_empty() else "chitchat"


def _action(i: Intent, pending: PendingFixture | None) -> str | None:
    a = i.answer_to_pending
    if pending is None or pending.kind is not PendingKind.LIMIT or a is None:
        return None
    if a.kind is A.YES or a.option_id == "continue":
        return "RESEARCH"
    return "REPORT" if a.kind is A.NO or a.option_id == "stop" else None


def _observed(i: Intent, before: CaseFile, after: CaseFile, request: str, action: str, latency: float) -> Observed:
    a = i.answer_to_pending
    return Observed(
        language=i.language, request=request, answer=AnswerKind(a.kind.value) if a else None,
        option_id=a.option_id if a else None, goals=tuple(GoalKind(g.kind.value) for g in i.goals),
        reaction=i.reaction.value if i.reaction else None,
        rejections=tuple((r.target_key, str(r.level)) for r in i.case_changes.rejections),
        replaced_keys=tuple(r.target_key for r in i.case_changes.replace_cars), before=before, after=after,
        delta_empty=i.case_changes.is_empty(), action=action, latency_ms=latency, model_called=True,
        notes=[f"{o.rule}: {o.field}" for o in i.overrides],
    )  # fmt: skip


def _refused(case: CaseFile, language: str, latency: float, why: str) -> Observed:
    return Observed(language=language, request=None, answer=None, option_id=None, goals=(), reaction=None,
                    rejections=(), replaced_keys=(), before=case, after=case, delta_empty=True, action="ASK",
                    latency_ms=latency, model_called=True, notes=[f"refused: {why}"])  # fmt: skip
