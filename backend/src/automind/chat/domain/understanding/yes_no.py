"""Yes and no in one form (spec 013 S3): what an option of an open question means, and the one form of an answer
that agrees or refuses — kind yes / no with the id of its button, whether it was tapped or typed. Pure."""

from __future__ import annotations

from automind.chat.domain.intake.option_ids import OptionKind
from automind.chat.domain.understanding.intent import AnswerKind, PendingAnswer
from automind.chat.domain.understanding.open_question import YES_NO, OpenKind, OpenQuestion


def meaning(kind: OpenKind, oid: str) -> AnswerKind | None:
    """What an option id of a question of `kind` means: yes, no, or nothing (a choice among several)."""
    if kind in YES_NO:
        (yes, _), (no, _) = YES_NO[kind]
        return AnswerKind.YES if oid == yes else AnswerKind.NO if oid == no else None
    head = oid.partition(":")[0]
    return AnswerKind.YES if head == OptionKind.YES else AnswerKind.NO if head == OptionKind.NO else None


def canonical_answer(a: PendingAnswer | None, q: OpenQuestion | None) -> PendingAnswer | None:
    """One form for "yes" and "no": an option that agrees or refuses is the answer yes / no with its id, and a typed
    yes / no names the one option of that meaning (the policy reads one kind; the record shows the button)."""
    if a is None or q is None or a.pending_id != q.id:
        return a
    if a.kind is AnswerKind.OPTION:
        o = q.option(a.option_id)
        return a if o is None or o.means is None else a.model_copy(update={"kind": o.means})
    same = [o.id for o in q.options if o.means is a.kind]
    return a.model_copy(update={"option_id": same[0]}) if a.option_id is None and len(same) == 1 else a
