"""Spec 013 S2 (T021): a rejection the model reads is kept only when the person's words are in the message and the
value is the car's current one (or left to it); a rejection of a value the car does not have, or of the very thing
the person wants, is dropped."""

from __future__ import annotations

from automind.chat.application.services.interpretation.contracts import Interpretation
from automind.chat.application.services.interpretation.stages.heard_rejections import heard_rejections
from automind.chat.domain.case import CaseCar, CaseFile

TEXT = "ты не нашел мерседес класс C. отменяй поиск"
WORDS = "ты не нашел мерседес класс C"


def _case(model: str) -> CaseFile:
    return CaseFile(cars=[CaseCar(key="car#1", request_text="Clase C", make="Mercedes-Benz", model=model)])


def _read(**kw: object) -> Interpretation:
    item = {"target_key": "car#1", "level": "MODEL", "evidence": WORDS, **kw}
    return Interpretation.model_validate({"request": "correction", "language": "ru",
                                          "delta": {"rejections": [item]}})  # fmt: skip


def _kept(case: CaseFile, i: Interpretation, text: str = TEXT) -> int:
    return len(heard_rejections(case, i, text).delta.rejections)


def test_the_owners_rejection_of_the_e_class_is_kept() -> None:
    assert _kept(_case("E-Class"), _read(value="E-Class", wanted="C-Class")) == 1
    assert _kept(_case("E-Class"), _read(wanted="C-Class")) == 1  # null: the current one


def test_a_value_the_car_does_not_have_is_dropped() -> None:
    assert _kept(_case("C-Class"), _read(value="E-Class", wanted="C-Class")) == 0


def test_rejecting_what_the_person_wants_is_dropped() -> None:
    assert _kept(_case("C-Class"), _read(wanted="C-Class")) == 0


def test_words_not_in_the_message_or_an_unknown_car_are_dropped() -> None:
    assert _kept(_case("E-Class"), _read(evidence="не тот класс")) == 0
    assert _kept(_case("E-Class"), _read(evidence="ok")) == 0
    assert _kept(_case("E-Class"), _read(target_key="car#7")) == 0


def test_without_rejections_the_reading_is_the_same_object() -> None:
    i = Interpretation(request="compare", language="ru")
    assert heard_rejections(_case("E-Class"), i, TEXT) is i
