"""Spec 013 S2 (T020): a rejection in the delta is recorded on its car before any replace — once, with the value the
car had — the rejected value leaves the car and its version is dropped; a replace of the same key keeps the memory;
old cases load without it."""

from __future__ import annotations

import pytest

from automind.chat.domain.case import CaseCar, CaseDelta, CaseFile, apply
from automind.chat.domain.identification.rejection import RejectLevel

NOW = 2026
WORDS = "ты не нашел мерседес класс C"


def _case() -> CaseFile:
    car = CaseCar(
        key="car#1",
        request_text="Clase C Berlina",
        make="Mercedes-Benz",
        model="E-Class",
        label="Mercedes-Benz E-Class W214 E 200 automatic",
        variant_id="v1",
        resolution="PROPOSED",
    )
    case = CaseFile(cars=[car], next_car_no=2)
    case.intake.card_confirmed = True
    return case


def _reject(**kw: object) -> CaseDelta:
    item = {"target_key": "car#1", "level": "MODEL", "evidence": WORDS, **kw}
    return CaseDelta.model_validate({"rejections": [item]})


def test_the_owners_chat_rejection_is_kept_and_the_model_becomes_the_one_wanted() -> None:
    new, log = apply(_case(), _reject(value="E-Class", wanted="C-Class"), current_year=NOW)
    car = new.cars[0]
    assert car.model == "C-Class" and car.variant_id is None and car.resolution == "UNRESOLVED"
    assert car.previous_label == "Mercedes-Benz E-Class W214 E 200 automatic"
    assert [(r.level, r.value, r.wanted, r.evidence) for r in car.identity_rejected] == [
        (RejectLevel.MODEL, "E-Class", "C-Class", WORDS)]  # fmt: skip
    assert not new.intake.card_confirmed and log == ["car#1: not E-Class — wants C-Class"]


def test_no_value_is_the_cars_current_one_and_no_wanted_leaves_the_model_open() -> None:
    car = apply(_case(), _reject(), current_year=NOW)[0].cars[0]
    assert car.identity_rejected[0].value == "E-Class" and car.model is None


def test_a_version_rejection_keeps_the_model_and_drops_the_version() -> None:
    car = apply(_case(), _reject(level="VERSION"), current_year=NOW)[0].cars[0]
    assert car.model == "E-Class" and car.label is None
    assert car.identity_rejected[0].value == "Mercedes-Benz E-Class W214 E 200 automatic"


def test_the_same_rejection_twice_is_kept_once() -> None:
    once, _ = apply(_case(), _reject(value="E-Class", wanted="C-Class"), current_year=NOW)
    twice, log = apply(once, _reject(value="e class"), current_year=NOW)
    assert len(twice.cars[0].identity_rejected) == 1 and log == []


def test_a_replace_of_the_same_key_keeps_what_was_rejected() -> None:
    delta = _reject(value="E-Class", wanted="C-Class").model_copy(update={"replace_cars": []})
    rejected, _ = apply(_case(), delta, current_year=NOW)
    replace = CaseDelta.model_validate({"replace_cars": [{"target_key": "car#1", "make": "Mercedes-Benz",
                                                          "model": "C-Class", "condition": "NEW"}]})  # fmt: skip
    car = apply(rejected, replace, current_year=NOW)[0].cars[0]
    assert car.condition == "NEW" and [r.value for r in car.identity_rejected] == ["E-Class"]


def test_an_unknown_car_raises_as_every_car_change() -> None:
    with pytest.raises(ValueError, match="unknown car reference"):
        apply(_case(), CaseDelta.model_validate({"rejections": [{"target_key": "car#9", "level": "MODEL",
                                                                 "evidence": WORDS}]}), current_year=NOW)  # fmt: skip


def test_an_old_case_without_rejections_loads() -> None:
    old = {"cars": [{"key": "car#1", "request_text": "Golf", "make": "Volkswagen", "model": "Golf"}]}
    assert CaseFile.model_validate(old).cars[0].identity_rejected == []
