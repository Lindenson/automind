"""The IntentResolver's rules (spec 013 T032, understanding-spec §5.2): each changes the intent only when it
applies, and every change is an Override naming the rule."""

from __future__ import annotations

from automind.chat.application.services.understanding import rules
from automind.chat.domain.case import CaseFile
from automind.chat.domain.understanding.intent import AnswerKind, GoalKind, Intent, IntentSource

from .builder import CARD, CASE, ENGINE_Q, ctx, question


def _intent(**fields: object) -> Intent:
    return Intent.model_validate({"source": IntentSource.TEXT, "language": "ru", **fields})


def _answer(p: object = None, kind: str = "yes", evidence: str = "да",
            option_id: str | None = None) -> dict[str, object]:  # fmt: skip
    return {"pending_id": p, "kind": kind, "evidence": evidence, "option_id": option_id}


def test_stale_pending_drops_an_answer_to_another_question_and_keeps_the_rest() -> None:
    i = _intent(answer_to_pending=_answer("q-old"), goals=[{"kind": "compare"}])
    out = rules.stale_pending(i, ctx(p=CARD))
    assert out.answer_to_pending is None and [g.kind for g in out.goals] == [GoalKind.COMPARE]
    assert [(o.rule, o.field, o.after) for o in out.overrides] == [("stale_pending", "answer_to_pending", None)]
    now = _intent(answer_to_pending=_answer(question(CARD).id))
    assert rules.stale_pending(now, ctx(p=CARD)) is now
    assert rules.stale_pending(now, ctx()).answer_to_pending is None  # nothing open any more


def test_a_complaint_is_not_an_answer_unless_it_names_one() -> None:
    q = question(ENGINE_Q)
    bare = _intent(reaction="complaint", answer_to_pending=_answer(q.id, "value", "ничего не нашел, плохо"))
    assert rules.complaint_is_not_an_answer(bare, ctx(p=ENGINE_Q)).answer_to_pending is None
    named = _intent(reaction="complaint", answer_to_pending=_answer(q.id, "option", "плохо, мне нужен 1.6 CRDi",
                                                                     "q:car#1:ENGINE:1"))  # fmt: skip
    assert rules.complaint_is_not_an_answer(named, ctx(p=ENGINE_Q)) is named
    yes = _intent(reaction="complaint", answer_to_pending=_answer(q.id, "yes", "да блин"))
    assert rules.complaint_is_not_an_answer(yes, ctx(p=ENGINE_Q)).overrides[0].rule == "complaint_is_not_an_answer"


def test_facts_on_the_open_question_answer_it_when_there_is_no_goal() -> None:
    diesel = {"set_car_context": [{"target_key": "car#1", "constraints": {"fuel_hint": "diesel"}}]}
    out = rules.no_goal_with_pending(_intent(case_changes=diesel), ctx(p=ENGINE_Q, text="хочу дизель"))
    assert out.answer_to_pending is not None and out.answer_to_pending.kind is AnswerKind.VALUE
    assert out.answer_to_pending.pending_id == question(ENGINE_Q).id
    other_car = {"set_car_context": [{"target_key": "car#2", "constraints": {"fuel_hint": "diesel"}}]}
    assert rules.no_goal_with_pending(_intent(case_changes=other_car), ctx(p=ENGINE_Q)).answer_to_pending is None
    asked = _intent(case_changes=diesel, goals=[{"kind": "ask_general", "question": "что такое DSG?"}])
    assert rules.no_goal_with_pending(asked, ctx(p=ENGINE_Q)) is asked


def test_two_makes_in_the_words_of_a_first_message_are_a_comparison() -> None:
    out = rules.cars_safety_net(_intent(), ctx(CaseFile(), text="kia или seat?"))
    assert [c.make for c in out.case_changes.add_cars] == ["Kia", "SEAT"]
    assert [g.kind for g in out.goals] == [GoalKind.COMPARE]
    assert [o.field for o in out.overrides] == ["case_changes.add_cars", "goals"]
    assert rules.cars_safety_net(_intent(), ctx(CASE, text="kia или seat?")).overrides == []  # the case has cars


def test_one_english_name_does_not_switch_a_russian_chat() -> None:
    earlier = ["я выбираю между двумя машинами"]
    out = rules.language_hysteresis(_intent(language="en"), ctx(text="Kia Sportage", earlier=earlier))
    assert out.language == "ru" and out.overrides[0].rule == "language_hysteresis"
    same = _intent(language="ru")
    assert rules.language_hysteresis(same, ctx(text="а дизель?", earlier=earlier)) is same
