"""What the person rejected about a car's identity, and the one filter that keeps it out of every proposal (spec 013
S2, I3: "a rejection is remembered").

A `Rejection` is a structured fact on the car ("not the E-Class", "not this E 200"): the level it is about, the
value rejected and, when the person said it, what they want instead. `exclude_rejected` is the only place a pool of
candidates (sourced versions, catalogue rows, the resolver's answer, ladder options, line-up models) loses what was
rejected; each candidate kind says its facts through a `FactsOf` adapter, so proposing a rejected candidate is
impossible whatever the strategy. Pure: no I/O; imports nothing of the case (the case imports this).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, Field

# --- contracts ------------------------------------------------------------------------------------------------------


class RejectLevel(StrEnum):
    """The level of the identity a rejection is about (the ladder's levels plus the model and the whole version)."""

    MODEL = "MODEL"
    GENERATION = "GENERATION"
    VERSION = "VERSION"
    ENGINE = "ENGINE"
    GEARBOX = "GEARBOX"
    DRIVE = "DRIVE"


class Rejection(BaseModel):
    """The person said "not this": `value` is what was rejected (resolved to the car's value at that moment, never
    empty), `wanted` what they want instead when they said it ("класс C"), `evidence` their words, `turn_seq` the
    turn it was said in when known."""

    model_config = ConfigDict(frozen=True)

    level: RejectLevel
    value: str = Field(min_length=1, max_length=160)
    wanted: str | None = Field(default=None, max_length=160)
    evidence: str = Field(default="", max_length=240)
    turn_seq: int | None = None


@dataclass(frozen=True)
class CandidateFacts:
    """What a candidate is, as far as a rejection can tell: its model, generation, the names of its version or
    engine ("E 200", "Mercedes-Benz E-Class W214 E 200 automatic"), its gearboxes and driven wheels."""

    model: str | None = None
    generation: str | None = None
    names: tuple[str, ...] = ()
    gearboxes: tuple[str, ...] = ()
    drives: tuple[str, ...] = ()


T = TypeVar("T")
T_contra = TypeVar("T_contra", contravariant=True)


class FactsOf(Protocol[T_contra]):
    """Reads the facts of one kind of candidate (a ladder version, a catalogue row, a choice, a model name)."""

    def __call__(self, candidate: T_contra, /) -> CandidateFacts: ...


# a version name may go on with words that do not change the engine: "E 200" is the version of "… E 200 automatic"
TRAILING_WORDS = frozenset({"automatic", "manual", "auto", "dsg", "dct", "cvt", "ecvt", "awd", "fwd", "rwd", "4wd",
                            "4x4", "4matic", "4motion", "quattro", "xdrive"})  # fmt: skip
_TOKEN = re.compile(r"[a-z0-9а-яё]+(?:\.[0-9]+)?")  # "2.0", "tdi", "w214", "класс"


# --- public API -----------------------------------------------------------------------------------------------------


def exclude_rejected(pool: Iterable[T], rejected: Sequence[Rejection], facts_of: FactsOf[T]) -> list[T]:
    """The candidates of `pool` that no rejection hits, in their order (all of them when nothing was rejected)."""
    items = list(pool)
    if not rejected:
        return items
    return [c for c in items if not is_rejected(facts_of(c), rejected)]


def is_rejected(facts: CandidateFacts, rejected: Sequence[Rejection]) -> bool:
    """A rejection hits the candidate: its model, generation or version is the rejected one, or every gearbox
    (driven wheels) it has was rejected."""
    return any(_hits(r, facts) for r in rejected)


def same_value(a: str | None, b: str | None) -> bool:
    """Two values name the same thing: case, spaces, hyphens and dots aside ("E-Class" = "e class")."""
    ca, cb = _compact(a or ""), _compact(b or "")
    return bool(ca) and ca == cb


def rejected_values(rejected: Sequence[Rejection], level: RejectLevel) -> list[str]:
    """The values rejected at one level, oldest first."""
    return [r.value for r in rejected if r.level is level]


# --- private helpers ------------------------------------------------------------------------------------------------


def _hits(r: Rejection, f: CandidateFacts) -> bool:
    if r.level is RejectLevel.MODEL:
        return same_value(r.value, f.model)
    if r.level is RejectLevel.GENERATION:
        return same_value(r.value, f.generation)
    if r.level is RejectLevel.GEARBOX:
        return bool(f.gearboxes) and all(same_value(r.value, g) for g in f.gearboxes)
    if r.level is RejectLevel.DRIVE:
        return bool(f.drives) and all(same_value(r.value, d) for d in f.drives)
    return any(_names_version(name, r.value) for name in f.names)  # VERSION, ENGINE


def _names_version(name: str, rejected: str) -> bool:
    """The candidate's version name is the rejected one: the same, or its words inside the rejected label followed
    only by gearbox/drive words ("E 200" in "Mercedes-Benz E-Class W214 E 200 automatic"; never "E 200" for
    "E 200 d")."""
    if same_value(name, rejected):
        return True
    want, have = _TOKEN.findall(name.lower()), _TOKEN.findall(rejected.lower())
    n = len(want)
    if not n:
        return False
    for i in range(len(have) - n + 1):
        if have[i : i + n] == want and all(w in TRAILING_WORDS for w in have[i + n :]):
            return True
    return False


def _compact(s: str) -> str:
    return "".join(_TOKEN.findall(s.lower())).replace(".", "")
