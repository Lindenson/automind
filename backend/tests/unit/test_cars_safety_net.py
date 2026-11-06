"""Live run 2026-11-04: "Сравни BYD Seal U DM-i и SEAT Ateca 1.5 TSI DSG" came back from the interpreter as a
general question with no cars. Two named cars are a comparison whatever the model says."""

from pathlib import Path

import pytest
import yaml

from automind.chat.application.services.interpretation.interpret import Interpretation
from automind.chat.dialog.nodes.understand import _cars_safety_net
from automind.chat.domain.case.casefile import CaseFile
from automind.chat.domain.intake.intake import cars_in_text
from automind.shared.vehicle.makes import MakeRegistry

REG = MakeRegistry.from_config(yaml.safe_load((Path(__file__).parents[2] / "config" / "makes.yaml").read_text()))
TEXT = "Сравни BYD Seal U DM-i и SEAT Ateca 1.5 TSI DSG. Семья, юг Испании (Малага), 12–24 тысячи км в год, новые."


@pytest.mark.parametrize(
    ("text", "want"),
    [
        (TEXT, [("BYD Seal U DM-i", "BYD"), ("SEAT Ateca 1.5 TSI DSG", "SEAT")]),
        ("Tesla Model 3 or BMW 320d?", [("Tesla Model 3", "Tesla"), ("BMW 320d", "BMW")]),
        ("¿Kia Sportage o Hyundai Tucson?", [("Kia Sportage", "Kia"), ("Hyundai Tucson", "Hyundai")]),
        ("Land Rover Defender vs Toyota Land Cruiser", [("Land Rover Defender", "Land Rover"),
                                                        ("Toyota Land Cruiser", "Toyota")]),
        ("Is BYD reliable?", [("BYD reliable", "BYD")]),
    ],
)  # fmt: skip
def test_cars_in_text(text, want):
    assert cars_in_text(text, REG.match_make) == want


def test_general_question_with_two_cars_becomes_a_comparison():
    i = Interpretation.model_validate({"request": "general_question", "language": "ru", "delta": {}})
    case, request, log = _cars_safety_net(CaseFile(), i, TEXT, REG, 2026, "general_question")
    assert request == "compare" and [c.make for c in case.cars] == ["BYD", "SEAT"]
    assert all(c.condition == "NEW" for c in case.cars) and log[0].startswith("cars from the user's words")
    ateca = case.cars[1].constraints.engine_hint
    assert ateca is not None and ateca.displacement_l == 1.5


def test_one_named_make_stays_a_general_question():
    i = Interpretation.model_validate({"request": "general_question", "language": "en", "delta": {}})
    case, request, log = _cars_safety_net(CaseFile(), i, "Is BYD reliable?", REG, 2026, "general_question")
    assert request == "general_question" and not case.cars and not log


def test_compare_without_cars_gets_them_from_the_words():
    i = Interpretation.model_validate({"request": "compare", "language": "ru", "delta": {}})
    case, request, _ = _cars_safety_net(CaseFile(), i, TEXT, REG, 2026, "compare")
    assert request == "compare" and len(case.cars) == 2


def test_context_for_a_car_added_in_the_same_message_is_folded_in():
    from automind.chat.application.services.interpretation.interpret import _check, _fold_new_car_context

    i = Interpretation.model_validate({"request": "compare", "language": "ru", "delta": {
        "add_cars": [{"request_text": "BYD Seal U DM-i", "make": "BYD", "model": "Seal U"},
                     {"request_text": "SEAT Ateca 1.5 TSI", "make": "SEAT", "model": "Ateca", "condition": "NEW"}],
        "set_car_context": [{"target_key": "car#1", "condition": "NEW"},
                            {"target_key": "car#2", "condition": "USED"}]}})  # fmt: skip
    out = _fold_new_car_context(CaseFile(), i)
    _check(CaseFile(), out.delta)  # no unknown reference any more
    assert out.delta.set_car_context == []
    assert [c.condition for c in out.delta.add_cars] == ["NEW", "NEW"]  # the add's own condition wins
