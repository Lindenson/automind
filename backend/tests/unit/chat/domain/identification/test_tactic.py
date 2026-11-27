"""Spec 013 S2 (T024): after a rejection, a dead end or the very question asked before widens the search; without a
rejection, or with a version found or a new question, the attempt is kept."""

from __future__ import annotations

from automind.chat.domain.case import Choice, IdentifyOutcome
from automind.chat.domain.identification.rejection import Rejection, RejectLevel
from automind.chat.domain.identification.tactic import Tactic, after_rejection, dead_end

REJECTED = [Rejection(level=RejectLevel.MODEL, value="E-Class", wanted="C-Class")]


def _asks(*labels: str, need: str = "ENGINE") -> IdentifyOutcome:
    return IdentifyOutcome.model_validate({"outcome": "CHOICES", "need": need, "level": need,
                                           "choices": [Choice(label=x) for x in labels]})  # fmt: skip


def test_without_a_rejection_nothing_changes() -> None:
    assert after_rejection([], None, IdentifyOutcome(outcome="NOT_FOUND", need="MODEL")) is Tactic.KEEP


def test_a_version_found_is_kept() -> None:
    assert after_rejection(REJECTED, None, IdentifyOutcome(outcome="IDENTIFIED")) is Tactic.KEEP


def test_a_dead_end_after_a_rejection_widens() -> None:
    assert after_rejection(REJECTED, None, IdentifyOutcome(outcome="NOT_FOUND", need="MODEL")) is Tactic.WIDEN
    assert dead_end(IdentifyOutcome(outcome="CHOICES", need="MODEL"))
    assert not dead_end(IdentifyOutcome(outcome="NEED", need="YEAR"))


def test_the_same_question_again_widens_a_new_one_is_kept() -> None:
    before = _asks("E 200", "E 220 d")
    assert after_rejection(REJECTED, before, _asks("E 220 d", "E 200")) is Tactic.WIDEN
    assert after_rejection(REJECTED, before, _asks("C 200", "C 300")) is Tactic.KEEP
    assert after_rejection(REJECTED, None, _asks("C 200", "C 300")) is Tactic.KEEP
