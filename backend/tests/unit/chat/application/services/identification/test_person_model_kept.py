"""Spec 013 T011 (I1): the model the person wrote is never replaced by a look-alike; it is kept, and when nothing is
found for it the look-alikes are asked back as "did you mean", the person's own name first."""

from __future__ import annotations

from automind.chat.application.services.identification.contracts import KnownModels
from automind.chat.application.services.identification.stages.ask_model import did_you_mean
from automind.chat.application.services.identification.stages.normalise_name import match_model
from automind.chat.domain.case import CaseCar, IdentifyOutcome
from automind.shared.vehicle.makes import MakeRegistry

REG = MakeRegistry.from_config({"makes": {"Mercedes-Benz": {"aliases": ["mercedes", "мерседес"]},
                                          "SEAT": {"aliases": ["сеат"]}}})  # fmt: skip
CHAT_D170B861 = {"E-Class", "CLA", "Clase S"}  # the known set of that chat: no C-Class


def _car(model: str | None, text: str = "") -> CaseCar:
    make = "SEAT" if "сеат" in text else "Mercedes-Benz"
    return CaseCar(key="car#1", request_text=text or f"Mercedes {model}", make=make, model=model)


def test_c_class_stays_c_class_and_e_class_is_only_suggested() -> None:
    car = _car("C-Class")
    suggestions = match_model(car, REG, CHAT_D170B861)
    assert car.model == "C-Class"
    assert "E-Class" in suggestions


def test_a_model_written_another_way_is_set_to_the_known_spelling() -> None:
    car = _car("Clase C")
    assert match_model(car, REG, {"C-Class", "E-Class"}) == []
    assert car.model == "C-Class"


def test_a_model_found_in_the_request_text() -> None:
    car = _car(None, "сеат атека")
    assert match_model(car, REG, {"Ateca", "Arona"}) == []
    assert car.model == "Ateca"


def test_nothing_found_asks_did_you_mean_with_the_persons_name_first() -> None:
    car = _car("C-Class")
    names = KnownModels(None, set(), CHAT_D170B861, ("E-Class", "CLA"))
    o = did_you_mean(car, names, IdentifyOutcome(outcome="NOT_FOUND", need="MODEL"))
    assert o.outcome == "CHOICES" and o.need == "MODEL"
    assert [c.model for c in o.choices] == ["C-Class", "E-Class", "CLA"]
    assert o.choices[0].suggested


def test_a_found_version_is_not_turned_into_a_question() -> None:
    car = _car("C-Class")
    names = KnownModels(None, set(), CHAT_D170B861, ("E-Class",))
    found = IdentifyOutcome(outcome="IDENTIFIED")
    assert did_you_mean(car, names, found) is found
