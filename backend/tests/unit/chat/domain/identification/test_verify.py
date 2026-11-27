"""Spec 013 S2 (T023; I2): a candidate is checked against the person's words before it is proposed — the model (no
look-alike), the make, the generation named, a used car's year, the engine named."""

from __future__ import annotations

from automind.acquisition.api import CatalogueVariant
from automind.chat.domain.case import CaseCar, Constraints
from automind.chat.domain.identification.verify import Fact, verify
from automind.shared.vehicle.identity import parse_engine


def _row(**kw: object) -> CatalogueVariant:
    base: dict[str, object] = dict(id="v1", make="Mercedes-Benz", model="E-Class", generation="W214",
                                   variant_name="E 200 automatic", powertrain="MHEV", generation_years_from=2023,
                                   engine_cc=1999, power_kw=150, fuel="mhev")  # fmt: skip
    return CatalogueVariant.model_validate({**base, **kw})


def _car(model: str, **kw: object) -> CaseCar:
    return CaseCar.model_validate({"key": "car#1", "request_text": f"Mercedes {model}", "make": "Mercedes-Benz",
                                   "model": model, **kw})  # fmt: skip


def test_the_e_class_contradicts_a_c_class() -> None:
    v = verify(_row(), _car("C-Class"))
    assert not v.ok and v.contradiction is not None
    assert (v.contradiction.fact, v.contradiction.person_said, v.contradiction.candidate_has) == (
        Fact.MODEL, "C-Class", "E-Class")  # fmt: skip


def test_the_same_model_written_otherwise_is_no_contradiction() -> None:
    assert verify(_row(model="C-Class"), _car("Clase C")).ok
    assert verify(_row(make="BYD", model="Seal U DM-i"), _car("Seal U", make="BYD")).ok
    assert verify(_row(make="Mercedes-Benz"), _car("E-Class", make="Mercedes")).ok


def test_another_make_is_a_contradiction() -> None:
    v = verify(_row(make="BMW", model="E-Class"), _car("E-Class"))
    assert v.contradiction is not None and v.contradiction.fact is Fact.MAKE


def test_the_generation_named() -> None:
    assert verify(_row(model="Land Cruiser Prado", generation="J150"),
                  _car("Land Cruiser Prado", constraints=Constraints(generation_hint="150"))).ok  # fmt: skip
    v = verify(_row(generation="W213"), _car("E-Class", constraints=Constraints(generation_hint="W214")))
    assert v.contradiction is not None and v.contradiction.fact is Fact.GENERATION


def test_a_used_cars_year_outside_the_generation() -> None:
    v = verify(_row(), _car("E-Class", condition="USED", year=2015))
    assert v.contradiction is not None and v.contradiction.fact is Fact.YEAR
    assert verify(_row(), _car("E-Class", condition="USED", year=2015, year_assumed=True)).ok  # assumed: not said
    assert verify(_row(), _car("E-Class", condition="NEW", year=2015)).ok


def test_the_engine_named() -> None:
    v = verify(_row(), _car("E-Class", constraints=Constraints(engine_hint=parse_engine("3.0 diesel"))))
    assert v.contradiction is not None and v.contradiction.fact is Fact.ENGINE
    assert verify(_row(), _car("E-Class", constraints=Constraints(engine_hint=parse_engine("2.0")))).ok
