"""Truth signals: evidence that a stored value is right or wrong, and where it came from (spec 010 US2, spec 011 US3).
Pure. `truth_signals.kind` / `.verdict` hold these values."""

from __future__ import annotations

from enum import StrEnum


class TruthKind(StrEnum):
    """Where a truth signal comes from."""

    CHALLENGE = "challenge"  # the user: "this value is wrong" (re-checked)
    BAD_SOURCE = "bad_source"  # the user: "this source is bad"
    REPLACEMENT = "replacement"  # a newer accepted value replaced the claim
    AGREEMENT = "agreement"  # independent families agree on the value
    GOLD = "gold"  # an official dataset says so
    PHYSICS = "physics"  # the value breaks a physical relation


class TruthVerdict(StrEnum):
    """What the signal says of the value."""

    RIGHT = "right"
    WRONG = "wrong"
