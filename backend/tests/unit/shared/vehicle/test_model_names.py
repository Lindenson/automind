"""Spec 013 T010 (I1): a model is set only by the person's words; look-alikes are suggestions."""

from __future__ import annotations

import pytest

from automind.shared.vehicle.model_names import match_model, suggest_models

MERCEDES = ["E-Class", "CLA", "C-Class", "Clase S"]


@pytest.mark.parametrize("text", ["c-class", "C-Class", "C Class", "Clase C", "Clase C Berlina", "класс С", "класс C",
                                  "мерседес класс C", "C Klasse"])  # fmt: skip
def test_the_class_the_person_wrote_is_kept(text: str) -> None:
    assert match_model(text, MERCEDES) == "C-Class"


def test_a_look_alike_class_is_never_chosen_only_suggested() -> None:
    known = ["E-Class", "CLA", "Clase S"]  # the chat d170b861 set: no C-Class
    assert match_model("c-class", known) is None
    assert match_model("Clase C", known) is None
    assert "E-Class" in suggest_models("c-class", known)


def test_another_cyrillic_class_letter_is_not_the_c_class() -> None:
    assert match_model("класс Е", ["C-Class", "CLA"]) is None


def test_the_longest_name_written_wins() -> None:
    assert match_model("Seal U", ["Seal", "Seal U"]) == "Seal U"
    assert match_model("Seal", ["Seal", "Seal U"]) == "Seal"
    assert match_model("Golf GTI", ["Golf", "Polo"]) == "Golf"
    assert match_model("CX-60", ["CX-6", "CX-60", "CX-30"]) == "CX-60"


@pytest.mark.parametrize(("text", "known", "want"), [
    ("атека", ["Ateca", "Arona", "Ibiza"], "Ateca"),
    ("туссан", ["Tucson", "Kona", "i30"], "Tucson"),
    ("сил ю", ["Seal", "Seal U", "Atto 3", "Dolphin"], "Seal U"),
    ("спортейдж", ["Sportage", "Ceed", "Niro"], "Sportage"),
])  # fmt: skip
def test_a_cyrillic_name_is_matched_by_its_sound(text: str, known: list[str], want: str) -> None:
    assert match_model(text, known) == want


def test_a_latin_misspelling_is_a_suggestion_not_a_match() -> None:
    assert match_model("Sportege", ["Sportage", "Ceed"]) is None
    assert suggest_models("Sportege", ["Sportage", "Ceed"]) == ["Sportage"]


def test_nothing_alike_suggests_nothing() -> None:
    assert match_model("квадрат", ["Sportage", "Ceed"]) is None
    assert suggest_models("квадрат", ["Sportage", "Ceed"]) == []
