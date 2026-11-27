"""validate_understanding (spec 013 T032, understanding-spec §5.1): the model's reading checked by code before
anything is resolved. It guesses no meaning; it keeps what the person's words carry and says what it dropped.

The checks of the old interpreter (`checks`: car keys, persona and profile words, numbers written in the message,
the engine from the words, rejections with their words) plus the open question's ids: an `option` answer must name
an option the question offers. Whether the answer is to the question open now is the resolver's (`stale_pending`).

A reading that names a car the case does not have is refused as a whole (`Validated.refused`), as the old
interpreter asks to rephrase instead of guessing; everything else only drops a part. Pure; never raises."""

from __future__ import annotations

from dataclasses import dataclass

from automind.chat.application.services.understanding import checks, engine
from automind.chat.domain.case import CaseFile
from automind.chat.domain.understanding.intent import AnswerKind, Goal, PendingAnswer, Understanding
from automind.chat.domain.understanding.open_question import OpenQuestion
from automind.chat.domain.understanding.record import Dropped


@dataclass(frozen=True)
class Validated:
    """The checked reading (None when refused), what the checks dropped, and why it was refused."""

    understanding: Understanding | None
    dropped: tuple[Dropped, ...] = ()
    refused: str | None = None


def validate_understanding(u: Understanding, case: CaseFile, question: OpenQuestion | None, text: str,
                           earlier: list[str]) -> Validated:  # fmt: skip
    """`u` checked against the case, the open question and the person's words (`text` this message, `earlier`
    their previous messages, newest last)."""
    d = checks.unknown_targets_as_new_cars(case, checks.fold_new_car_context(case, u.case_changes))
    bad = checks.unknown_refs(case, d)
    if bad:
        return Validated(None, refused=f"unknown car reference(s): {', '.join(bad)}")
    said = [text, *reversed(earlier)]
    d, persona = checks.persona_from_words(d, u.persona_evidence, said)
    d, profile = checks.profile_from_words(d, said)
    d, numbers = checks.constraints_from_message(d, text)
    d, rejections = checks.heard_rejections(case, engine.engine_hints(d, text), text)
    goals, focus = _known_focus(u.goals, case, len(d.add_cars))
    answer, answered = _answer(u, question)
    dropped = (*persona, *profile, *numbers, *rejections, *focus, *answered)
    return Validated(u.model_copy(update={"case_changes": d, "goals": goals, "answer_to_pending": answer}), dropped)


def _known_focus(goals: list[Goal], case: CaseFile, added: int) -> tuple[list[Goal], list[Dropped]]:
    """Goals with only the car keys the case has (or gets from this message)."""
    keys = {c.key for c in case.cars} | {f"car#{case.next_car_no + n}" for n in range(added)}
    out: list[Goal] = []
    dropped: list[Dropped] = []
    for g in goals:
        unknown = [k for k in g.focus_cars if k not in keys]
        if unknown:
            dropped.append(Dropped(check="known_cars", field=f"goals.{g.kind}.focus_cars",
                                   why=f"no car {', '.join(unknown)} in the case"))  # fmt: skip
            g = g.model_copy(update={"focus_cars": [k for k in g.focus_cars if k in keys]})
        out.append(g)
    return out, dropped


def _answer(u: Understanding, question: OpenQuestion | None) -> tuple[PendingAnswer | None, list[Dropped]]:
    """The answer, unless it picks an option the open question does not offer."""
    a = u.answer_to_pending
    if a is None or question is None or a.pending_id != question.id or a.kind is not AnswerKind.OPTION:
        return a, []
    if question.option(a.option_id) is not None:
        return a, []
    return None, [Dropped(check="known_option", field="answer_to_pending.option_id",
                          why=f"{a.option_id!r} is not an option of {question.id}")]  # fmt: skip
