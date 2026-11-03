"""Identification loop and equal level (spec 004 US8, FR-029–FR-031)."""

from __future__ import annotations

from rapidfuzz import fuzz

from automind.domain import identification as idf
from automind.domain.casefile import CaseCar, Constraints


def car(**kw) -> CaseCar:
    return CaseCar(key="car#1", request_text=kw.pop("request_text", "Mazda CX-5"), **kw)


def test_settled_only_when_confirmed_or_unique() -> None:
    assert idf.settled(car()) == (False, "NO_MAKE_MODEL")
    assert idf.settled(car(make="Mazda", model="CX-5")) == (False, "UNRESOLVED")
    assert idf.settled(car(make="Mazda", model="CX-5", variant_id="v", resolution="PROPOSED")) == (False, "PROPOSED")
    assert idf.settled(car(make="Mazda", model="CX-5", variant_id="v", resolution="CONFIRMED"))[0]
    assert idf.settled(car(make="Mazda", model="CX-5", variant_id="v", resolution="AUTO_OK"))[0]
    assert idf.settled(car(make="Toyota", model="Rav7", resolution="UNKNOWN_MODEL")) == (False, "UNKNOWN_MODEL")


def test_nonsense_does_not_answer_a_car_question() -> None:
    before = car(request_text="that one")
    assert not idf.answer_settles("CAR_IDENTITY", before, before, "compare")
    assert idf.answer_settles("CAR_IDENTITY", before, car(make="Mazda", model="CX-5"), "compare")
    assert idf.answer_settles("CAR_IDENTITY", before, None, "compare")  # removed


def test_variant_proposal_needs_a_yes_a_no_a_choice_or_a_change() -> None:
    c = car(make="Mazda", model="CX-5", variant_id="v", resolution="PROPOSED")
    assert not idf.answer_settles("CONFIRM_VARIANTS", c, c, "compare")
    for request in ("confirm_yes", "confirm_no", "choose_for_me"):
        assert idf.answer_settles("CONFIRM_VARIANTS", c, c, request)
    diesel = c.model_copy(update={"constraints": Constraints(fuel_hint="diesel")})
    assert idf.answer_settles("CONFIRM_VARIANTS", c, diesel, "correction")


def test_used_age_needs_a_year_or_an_age() -> None:
    c = car(make="BMW", model="3 Series", condition="USED")
    assert not idf.answer_settles("USED_AGE", c, c, "compare")
    assert idf.answer_settles("USED_AGE", c, c.model_copy(update={"age_years": 6}), "compare")


def test_level_defaults_to_base_and_follows_a_named_version() -> None:
    assert idf.level_for([None, None]) == ("BASE", "DEFAULT")
    assert idf.level_for([None, "TOP"]) == ("TOP", "USER_TRIM")
    assert [idf.level_in_range(i, 5) for i in range(5)] == ["BASE", "MID", "MID", "MID", "TOP"]
    assert idf.level_in_range(0, 1) == "BASE"


def test_closest_models() -> None:
    known = {"RAV4", "C-HR", "Corolla", "Land Cruiser Prado", "Yaris"}
    assert idf.closest_models("Rav7", known, fuzz.WRatio)[0] == "RAV4"
    assert idf.closest_models("zzzz", known, fuzz.WRatio) == []
