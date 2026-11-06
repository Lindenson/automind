"""Chat 9b5c0b0c (2026-11-04): "Audi A4 2.5 l second hand, 50,000 km" then "2023". No A4 of 2023 has a 2.5; the
hub offered B5/B6/B7 2.5 TDI anyway, the user picked one, the year conflict blocked it, and "remove or choose?"
was asked forever: "Выбери сам" and "Да вперед к сравнению" were not understood."""

from types import SimpleNamespace

import pytest

from automind.chat.application.services.identification.stages.offer_engines import year_conflict
from automind.chat.dialog import phrases
from automind.chat.domain import intake
from automind.chat.domain.case import CaseCar, CaseFile, Choice, Constraints, Pending
from automind.shared.vehicle.engine import EngineHint

REF = SimpleNamespace(generations={"Audi|A4": [("B8", 2008, 2015), ("B9", 2015, 2024)]})


def _audi(**kw) -> CaseCar:
    kw = {"model": "A4", "year": 2023, **kw}
    return CaseCar(key="car#1", request_text="audi A4 2.5 l second hand with 50000 km", make="Audi",
                   condition="USED", mileage_km=50000,
                   constraints=Constraints(engine_hint=EngineHint(displacement_l=2.5, fuel="diesel", family="TDI")),
                   **kw)  # fmt: skip


def _pick(case: CaseFile, text: str):
    return intake.pick(case, text, gearbox_words=phrases.GEARBOX_WORDS, yes=phrases.yes_or_no(text) == "yes",
                       choose=phrases.choose_for_me(text) or phrases.go_ahead(text))  # fmt: skip


@pytest.mark.parametrize("text", ["Выбери сам", "Да вперед к сравнению", "choose for me", "Elige tú", "Да"])
def test_remove_or_choose_answered_by_choose_lets_the_hub_choose(text):
    case = CaseFile(cars=[_audi()], pending=Pending(kind="QUESTIONS", items=[
        {"kind": "REMOVE_OR_CHOOSE", "car": "car#1", "item": "CHOICE", "choices": []}]))  # fmt: skip
    case.intake.attempts["car#1"] = {"ENGINE": 2, "CHOICE": 2}
    new, log = _pick(case, text)
    car = new.car("car#1")
    assert car.constraints.engine_hint is None and car.chosen_for_me
    assert car.year == 2023 and car.mileage_km == 50000  # the facts that remain decide
    assert car.request_text == "Audi A4"  # the 2.5 l is not sent to the resolver again
    assert "car#1" not in new.intake.attempts and "choose for me" in log[0]
    assert intake.next_step(new).kind != "REMOVE_OR_CHOOSE"


def test_choose_on_an_engine_list_takes_the_first_option():
    ch = [Choice(label="Audi A4 B9 2.0 TDI 150 PS", make="Audi", model="A4"),
          Choice(label="Audi A4 B9 2.0 TFSI 150 PS", make="Audi", model="A4")]  # fmt: skip
    case = CaseFile(cars=[_audi()], pending=Pending(kind="QUESTIONS", items=[
        {"kind": "ENGINE", "car": "car#1", "item": "ENGINE", "choices": [c.model_dump() for c in ch]}]))  # fmt: skip
    new, _ = _pick(case, "Выбери сам")
    car = new.car("car#1")
    assert car.chosen_for_me and car.constraints.engine_hint is not None
    assert car.constraints.engine_hint.displacement_l == 2.0


@pytest.mark.parametrize(
    ("label", "conflict"),
    [
        ("Audi A4 B5 2.5 TDI", True),  # unknown to config, and config knows the 2023 generation (B9)
        ("Audi A4 B6 2.5 TDI V6", True),
        ("Audi A4 B8 2.0 TDI", True),  # known: 2008–2015
        ("Audi A4 B9 2.0 TDI 150 PS", False),
        ("Audi A4 2.0 TDI 150 PS", False),  # no generation named
        ("Audi A4 3.0 TDI V6 quattro", False),  # V6 is not a generation
    ],
)
def test_options_from_another_generation_than_the_year_are_not_offered(label, conflict):
    assert year_conflict(label, _audi(), REF) is conflict


def test_no_year_or_no_config_no_filter():
    assert not year_conflict("Audi A4 B5 2.5 TDI", _audi(year=None), REF)
    assert not year_conflict("Audi A6 C5 2.5 TDI", _audi(model="A6"), REF)


@pytest.mark.parametrize(("text", "go"), [("Да вперед к сравнению", True), ("go ahead", True), ("adelante", True),
                                          ("а какая надёжнее?", False), ("давление в шинах", False)])  # fmt: skip
def test_go_ahead(text, go):
    assert phrases.go_ahead(text) is go
