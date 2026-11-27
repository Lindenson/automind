"""The open question as the understanding step sees it (spec 013 T031): a stable id from the stored pending, and
options with the ids the chips send."""

from __future__ import annotations

from automind.chat.domain.case import Pending
from automind.chat.domain.understanding.intent import AnswerKind, PendingAnswer
from automind.chat.domain.understanding.open_question import OpenKind, limit_question, open_question, pending_id
from automind.chat.domain.understanding.yes_no import canonical_answer, meaning


def _ids(p: Pending) -> list[str]:
    q = open_question(p)
    assert q is not None
    return [o.id for o in q.options]


def test_nothing_open_is_none() -> None:
    assert open_question(None) is None


def test_the_id_is_stable_for_a_pending_and_differs_for_another() -> None:
    a = Pending(kind="QUESTIONS", items=[{"kind": "USED_AGE", "car": "car#2", "text": "How old?"}])
    again = Pending.model_validate(a.model_dump(mode="json"))  # read back from the stored case file
    other = Pending(kind="QUESTIONS", items=[{"kind": "ENGINE", "car": "car#2", "text": "Which engine?"}])
    assert pending_id(a) == pending_id(again) != pending_id(other)
    assert pending_id(a).startswith("q-") and open_question(a).id == pending_id(a)  # type: ignore[union-attr]


def test_questions_carry_the_ids_of_their_chips() -> None:
    p = Pending(kind="QUESTIONS", items=[
        {"kind": "TRIM", "car": "car#1", "text": "Which version?", "choices": [{"label": "Base"}, {"label": "Top"}]},
        {"kind": "GEARBOX", "car": "car#2", "text": "Which gearbox?"},
        {"kind": "CONDITION", "text": "New or used?"},
    ])  # fmt: skip
    q = open_question(p)
    assert q is not None and q.cars == ("car#1", "car#2")
    assert [o.id for o in q.options] == [
        "q:car#1:TRIM:0", "q:car#1:TRIM:1", "gb:car#2:automatic", "gb:car#2:manual", "condition:NEW", "condition:USED",
        "choose", "remove:car#1", "remove:car#2",
    ]  # fmt: skip
    assert q.option("q:car#1:TRIM:1").label == "Top"  # type: ignore[union-attr]
    assert q.question == "Which version? Which gearbox? New or used?"


def test_a_proposal_is_yes_or_another_one() -> None:
    p = Pending(kind="QUESTIONS", items=[{"kind": "PROPOSE", "car": "car#1", "text": "Is it the C 200?"}])
    assert _ids(p) == ["yes:car#1", "no:car#1", "remove:car#1"]


def test_confirmations_offer_their_buttons() -> None:
    variants = Pending(kind="CONFIRM_VARIANTS", items=[{"car": "car#1", "options": [
        {"id": "option:car#1:v1", "label": "Golf 1.5"}, {"id": "remove:car#1", "label": "remove"}]}])  # fmt: skip
    assert _ids(variants) == ["option:car#1:v1", "remove:car#1", "choose"]
    assert _ids(Pending(kind="CONFIRM_COST", items=[{"eur": 0.4, "cars": ["car#1"]}])) == ["run", "skip"]
    assert _ids(Pending(kind="CONFIRM_INTAKE", items=[{"car": "car#1"}])) == ["yes", "stop"]


def test_the_research_limit_is_a_question_of_its_own() -> None:
    q = limit_question("limit-1")
    assert (q.id, q.kind, [o.id for o in q.options]) == ("limit-1", "LIMIT", ["continue", "stop"])


def test_yes_and_no_have_one_form_whether_typed_or_tapped() -> None:
    card = open_question(Pending(kind="CONFIRM_INTAKE", items=[{"car": "car#1"}]))
    assert card is not None
    tapped = PendingAnswer(pending_id=card.id, kind=AnswerKind.OPTION, option_id="stop", evidence="Not now")
    typed = PendingAnswer(pending_id=card.id, kind=AnswerKind.NO, evidence="not now")
    assert canonical_answer(tapped, card) == tapped.model_copy(update={"kind": AnswerKind.NO})
    assert canonical_answer(typed, card) == typed.model_copy(update={"option_id": "stop"})
    other = PendingAnswer(pending_id="q-other", kind=AnswerKind.OPTION, option_id="stop", evidence="x")
    assert canonical_answer(other, card) is other and canonical_answer(None, card) is None


def test_what_an_option_id_means() -> None:
    assert (
        meaning(OpenKind.LIMIT, "continue") is AnswerKind.YES
        and meaning(OpenKind.CONFIRM_COST, "skip") is AnswerKind.NO
    )
    assert (
        meaning(OpenKind.QUESTIONS, "no:car#1") is AnswerKind.NO
        and meaning(OpenKind.QUESTIONS, "q:car#1:TRIM:0") is None
    )
