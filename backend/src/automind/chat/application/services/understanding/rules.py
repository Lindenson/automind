"""The rules of the IntentResolver (spec 013 T032, understanding-spec §5.2, §D1): the only code that may change what
was understood. Each rule is a named function `(intent, Context) -> intent`; a change appends an `Override` (rule,
field, before, after, why), so every correction is visible in the turn's record. A rule that does not apply returns
the intent unchanged. Pure.

Order (`TEXT_RULES`): `stale_pending` → `complaint_is_not_an_answer` → `no_goal_with_pending` → `cars_safety_net` →
`language_hysteresis`. A button runs `option_from_ui` first (in `resolver`) and then `stale_pending`."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from pydantic import BaseModel

from automind.chat.domain import understanding
from automind.chat.domain.case import CarRef, CaseDelta, CaseFile, Constraints
from automind.chat.domain.understanding.intent import (
    AnswerKind,
    Goal,
    GoalKind,
    Intent,
    Override,
    PendingAnswer,
    Reaction,
)
from automind.chat.domain.understanding.open_question import OpenKind, OpenQuestion
from automind.shared.contracts.config import MakeNames
from automind.shared.vehicle.identity import parse_engine

MAX_FOUND = 3  # at most three cars are compared
EVIDENCE_CHARS = 200


class LanguageWords(Protocol):
    """The chat's language with hysteresis (implemented by the dialog's `phrases`)."""

    def stable_language(self, detected: str | None, current: str, earlier: list[str]) -> str | None:
        """One English model name does not switch a Russian chat."""
        ...

    def guess_language(self, texts: list[str]) -> str:
        """The language of the person's words (for a button without text)."""
        ...


@dataclass(frozen=True)
class Context:
    """What the rules look at besides the intent: the case before the message, the open question, the words."""

    case: CaseFile
    question: OpenQuestion | None
    text: str  # the person's words ("" for a button)
    earlier: list[str] = field(default_factory=list)  # the person's earlier messages, oldest first
    words: LanguageWords | None = None
    makes: MakeNames | None = None


Rule = Callable[[Intent, Context], Intent]


def stale_pending(i: Intent, ctx: Context) -> Intent:
    """An answer to a question that is not the open one (or to none) is dropped; the rest of the intent stays."""
    a = i.answer_to_pending
    if a is None or (ctx.question is not None and a.pending_id == ctx.question.id):
        return i
    now = ctx.question.id if ctx.question else "none"
    return _set(i, "stale_pending", "answer_to_pending", None, f"answers {a.pending_id}, the open question is {now}")


def complaint_is_not_an_answer(i: Intent, ctx: Context) -> Intent:
    """A complaint answers the open question only with an explicit value or option in its words (spec 013 §D1):
    "ничего не нашел, плохо" is never "yes", nor the answer to the engine question."""
    a = i.answer_to_pending
    if i.reaction is not Reaction.COMPLAINT or a is None or _explicit(a, i.case_changes, ctx):
        return i
    return _set(i, "complaint_is_not_an_answer", "answer_to_pending", None,
                f"a complaint ({a.evidence!r}) does not answer {a.pending_id}")  # fmt: skip


def no_goal_with_pending(i: Intent, ctx: Context) -> Intent:
    """No goal and no answer, but facts about what the open question asks: they answer it (kind `value`). Replaces
    the old "while a question is open every message is an answer"."""
    q = ctx.question
    if (
        q is None
        or q.kind is not OpenKind.QUESTIONS
        or i.goals
        or i.answer_to_pending
        or not _on_topic(i.case_changes, q)
    ):
        return i
    a = PendingAnswer(pending_id=q.id, kind=AnswerKind.VALUE, evidence=ctx.text[:EVIDENCE_CHARS])
    return _set(i, "no_goal_with_pending", "answer_to_pending", a, "the message states facts the question asks")


def cars_safety_net(i: Intent, ctx: Context) -> Intent:
    """No car in the case, none read, no open question: two or more makes in the words are a comparison of their
    cars (moved from the old `apply`, live run 2026-11-04)."""
    if ctx.case.cars or ctx.question is not None or i.case_changes.add_cars or ctx.makes is None:
        return i
    found = understanding.cars_in_text(ctx.text, ctx.makes.match_make)
    if len(found) < 2:
        return i
    cond = understanding.condition_of(ctx.text) or "UNKNOWN"
    refs = [CarRef(request_text=words, make=make, condition=cond,
                   constraints=Constraints(engine_hint=parse_engine(words)))
            for words, make in found[:MAX_FOUND]]  # fmt: skip
    changes = i.case_changes.model_copy(update={"add_cars": refs})
    out = _set(i, "cars_safety_net", "case_changes.add_cars", changes,
               "makes named in the words; the model read no car", shown=[r.request_text for r in refs])  # fmt: skip
    if any(g.kind is GoalKind.COMPARE for g in i.goals):
        return out
    goals = [Goal(kind=GoalKind.COMPARE), *i.goals]
    return out.model_copy(update={"goals": goals, "overrides": [*out.overrides, Override(
        rule="cars_safety_net", field="goals", before=[g.kind.value for g in i.goals],
        after=[g.kind.value for g in goals], why="two named cars are a comparison")]})  # fmt: skip


def language_hysteresis(i: Intent, ctx: Context) -> Intent:
    """The chat's stable language: one message with an English model name does not switch a Russian chat."""
    if ctx.words is None:
        return i
    lang = ctx.words.stable_language(i.language, ctx.text, ctx.earlier)
    if lang is None or lang == i.language:
        return i
    return _set(i, "language_hysteresis", "language", lang, "the chat's language holds for this message")


TEXT_RULES: tuple[Rule, ...] = (stale_pending, complaint_is_not_an_answer, no_goal_with_pending, cars_safety_net,
                                language_hysteresis)  # fmt: skip


def _set(i: Intent, rule: str, path: str, after: object, why: str, shown: object = None) -> Intent:
    """`i` with the field at `path` set to `after` and the override recorded (`shown`: what the record shows as
    after, when not `after` itself)."""
    head = path.split(".")[0]
    before = getattr(i, head)
    o = Override(rule=rule, field=path, before=_plain(before, path), after=_plain(after, path) if shown is None
                 else shown, why=why)  # fmt: skip
    return i.model_copy(update={head: after, "overrides": [*i.overrides, o]})


def _plain(value: object, path: str) -> object:
    """A JSON-friendly value for the record: a model as its dump, the sub-field of a path into it."""
    if isinstance(value, CaseDelta) and "." in path:
        return [r.request_text for r in value.add_cars] if path.endswith("add_cars") else None
    return value.model_dump(mode="json") if isinstance(value, BaseModel) else value


def _explicit(a: PendingAnswer, changes: CaseDelta, ctx: Context) -> bool:
    """The answer names an offered option or states a fact the question asks."""
    if a.kind not in (AnswerKind.OPTION, AnswerKind.VALUE) or ctx.question is None:
        return False
    said = a.evidence.casefold()
    named = any(o.label.casefold() in said for o in ctx.question.options if len(o.label) >= 2)
    return named or _on_topic(changes, ctx.question)


def _on_topic(d: CaseDelta, q: OpenQuestion) -> bool:
    """The changes touch a car the question is about (or, for a question about no car, any car or the budget)."""
    touched = {x.target_key for x in (*d.set_car_context, *d.replace_cars)}
    if q.cars:
        return bool(touched & set(q.cars))
    return bool(touched) or (d.set_budget is not None and d.set_budget.intent != "UNKNOWN")
