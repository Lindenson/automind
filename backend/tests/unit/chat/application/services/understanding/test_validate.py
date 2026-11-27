"""validate_understanding (spec 013 T032): the old interpreter's checks over an Understanding, plus the open
question's option ids; a car the case does not have refuses the reading."""

from __future__ import annotations

from automind.chat.application.services.understanding.validate import validate_understanding

from .builder import CASE, ENGINE_Q, question, understanding


def test_a_car_the_case_does_not_have_refuses_the_reading() -> None:
    u = understanding(case_changes={"remove_cars": ["car#7"]})
    v = validate_understanding(u, CASE, None, "убери седьмую", [])
    assert v.understanding is None and v.refused == "unknown car reference(s): car#7"


def test_numbers_not_in_the_message_and_a_persona_without_words_are_dropped() -> None:
    u = understanding(case_changes={"set_budget": {"max_eur": 50000, "intent": "UNKNOWN"},
                                    "set_persona": {"persona": "BUYER", "source": "INFERRED"}},
                      persona_evidence="не хочу переплачивать")  # fmt: skip
    v = validate_understanding(u, CASE, None, "а что дешевле в обслуживании?", [])
    assert v.understanding is not None
    assert v.understanding.case_changes.set_budget is None and v.understanding.case_changes.set_persona is None
    assert [(d.check, d.field) for d in v.dropped] == [("persona_words", "set_persona"),
                                                       ("numbers_in_message", "set_budget.max_eur")]  # fmt: skip


def test_an_option_the_question_does_not_offer_is_dropped_and_an_offered_one_kept() -> None:
    q = question(ENGINE_Q)
    bad = understanding(answer_to_pending={"pending_id": q.id, "kind": "option", "option_id": "q:car#1:ENGINE:7",
                                           "evidence": "дизель"})  # fmt: skip
    good = understanding(answer_to_pending={"pending_id": q.id, "kind": "option", "option_id": "q:car#1:ENGINE:1",
                                            "evidence": "CRDi"})  # fmt: skip
    dropped = validate_understanding(bad, CASE, q, "дизель", [])
    assert dropped.understanding.answer_to_pending is None  # type: ignore[union-attr]
    assert [d.check for d in dropped.dropped] == ["known_option"]
    kept = validate_understanding(good, CASE, q, "CRDi", [])
    assert kept.understanding.answer_to_pending.option_id == "q:car#1:ENGINE:1" and not kept.dropped  # type: ignore[union-attr]


def test_a_goal_keeps_only_the_cars_the_case_has_or_gets() -> None:
    u = understanding(goals=[{"kind": "compare", "focus_cars": ["car#1", "car#3", "car#9"]}],
                      case_changes={"add_cars": [{"request_text": "BMW", "make": "BMW"}]})  # fmt: skip
    v = validate_understanding(u, CASE, None, "сравни с BMW", [])
    assert v.understanding.goals[0].focus_cars == ["car#1", "car#3"]  # type: ignore[union-attr]
    assert [d.field for d in v.dropped] == ["goals.compare.focus_cars"]


def test_a_rejection_without_the_words_is_dropped_and_one_with_them_kept() -> None:
    rejection = {"target_key": "car#2", "level": "MODEL", "value": "E-Class", "wanted": "C-Class"}
    said = understanding(case_changes={"rejections": [{**rejection, "evidence": "ты не нашел класс C"}]})
    unsaid = understanding(case_changes={"rejections": [{**rejection, "evidence": "это не E-класс"}]})
    assert len(validate_understanding(said, CASE, None, "ты не нашел класс C", []).understanding.case_changes  # type: ignore[union-attr]
               .rejections) == 1  # fmt: skip
    v = validate_understanding(unsaid, CASE, None, "ты не нашел класс C", [])
    assert v.understanding.case_changes.rejections == [] and v.dropped[0].check == "heard_rejections"  # type: ignore[union-attr]


def test_the_model_the_person_asked_for_is_never_rejected_without_another_one() -> None:
    asked = CASE.model_copy(deep=True)
    asked.cars[1].model, asked.cars[1].request_text = "C-Class", "мерседес Clase C"  # found as asked
    said = "ты не нашел мерседес класс C"
    bare = understanding(case_changes={"rejections": [{"target_key": "car#2", "level": "MODEL", "value": "C-Class",
                                                       "evidence": said}]})  # fmt: skip
    v = validate_understanding(bare, asked, None, said, [])
    assert v.understanding.case_changes.rejections == [] and v.dropped[0].check == "heard_rejections"  # type: ignore[union-attr]
    other = understanding(case_changes={"rejections": [{"target_key": "car#2", "level": "MODEL", "value": "C-Class",
                                                        "wanted": "CLA", "evidence": said}]})  # fmt: skip
    assert len(validate_understanding(other, asked, None, said, []).understanding.case_changes.rejections) == 1  # type: ignore[union-attr]


def test_the_engine_is_read_from_the_words() -> None:
    u = understanding(case_changes={"set_car_context": [{"target_key": "car#1", "constraints": {"trim_hint": "1.6"}}]})
    v = validate_understanding(u, CASE, None, "мне нужен 1.6", [])
    k = v.understanding.case_changes.set_car_context[0].constraints  # type: ignore[union-attr]
    assert k is not None and k.trim_hint is None and k.engine_hint is not None and k.engine_hint.displacement_l == 1.6
