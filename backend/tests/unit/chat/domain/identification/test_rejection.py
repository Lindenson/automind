"""Spec 013 S2 (T020, T022; I3): a rejection is a structured fact, and the one filter keeps every rejected candidate
out — a model, a generation, a version (by its words inside the rejected label), a gearbox, driven wheels."""

from __future__ import annotations

from automind.chat.domain.identification.rejection import (
    CandidateFacts,
    Rejection,
    RejectLevel,
    exclude_rejected,
    is_rejected,
    same_value,
)

E_CLASS = Rejection(level=RejectLevel.MODEL, value="E-Class", wanted="C-Class", evidence="ты не нашел класс C")
E_200 = Rejection(level=RejectLevel.VERSION, value="Mercedes-Benz E-Class W214 E 200 automatic", evidence="не то")


def _model(name: str) -> CandidateFacts:
    return CandidateFacts(model=name)


def test_a_rejected_model_is_filtered_whatever_its_spelling() -> None:
    assert exclude_rejected(["C-Class", "e class", "E-Class", "CLA"], [E_CLASS], _model) == ["C-Class", "CLA"]


def test_nothing_rejected_keeps_the_pool_as_it_is() -> None:
    pool = ["E-Class", "C-Class"]
    assert exclude_rejected(pool, [], _model) == pool


def test_a_version_is_hit_by_its_words_inside_the_rejected_label() -> None:
    assert is_rejected(CandidateFacts(names=("E 200",)), [E_200])
    assert is_rejected(CandidateFacts(names=("Mercedes-Benz E-Class W214 E 200 automatic",)), [E_200])


def test_another_engine_of_the_same_numbers_is_not_hit() -> None:
    assert not is_rejected(CandidateFacts(names=("E 200 d",)), [Rejection(level=RejectLevel.ENGINE, value="E 200")])
    assert not is_rejected(CandidateFacts(names=("E 220 d",)), [E_200])
    assert not is_rejected(CandidateFacts(names=("2.0",)), [Rejection(level=RejectLevel.ENGINE, value="2.0 TDI")])


def test_a_gearbox_hits_only_a_candidate_with_nothing_else() -> None:
    manual = [Rejection(level=RejectLevel.GEARBOX, value="manual")]
    assert is_rejected(CandidateFacts(gearboxes=("manual",)), manual)
    assert not is_rejected(CandidateFacts(gearboxes=("manual", "dct")), manual)
    assert not is_rejected(CandidateFacts(), manual)  # unknown gearbox: never excluded by it


def test_generation_and_drive() -> None:
    assert is_rejected(CandidateFacts(generation="W214"), [Rejection(level=RejectLevel.GENERATION, value="w214")])
    assert is_rejected(CandidateFacts(drives=("AWD",)), [Rejection(level=RejectLevel.DRIVE, value="awd")])


def test_same_value_never_matches_empty_words() -> None:
    assert same_value("E-Class", "e class")
    assert same_value("класс С", "Класс с")
    assert not same_value("", "")
    assert not same_value(None, "E-Class")
    assert not same_value("-", "/")
