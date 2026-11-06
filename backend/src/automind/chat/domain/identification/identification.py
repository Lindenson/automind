"""Identification loop and equal equipment level (spec 004 US8, FR-029–FR-031; research R14). Pure.

- `settled`: a car is settled when make and model are known, the model exists, and its variant was confirmed by
  the user or is the only catalog fit. Research never starts on an unsettled car (FR-030).
- `answer_settles`: whether the user's message answered a car question. A message that does not (nonsense,
  another topic) leaves the question open, so it is asked again (FR-031).
- `level_for`: the equipment level all cars are compared at. A version the user named sets it; otherwise the
  base version (FR-029).
- `closest_models`: known models close to an unknown name (the scorer is passed in, so domain stays free of
  libraries).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from typing import Literal

from automind.chat.domain.case.casefile import CaseCar

Level = Literal["BASE", "MID", "TOP"]
LevelSource = Literal["DEFAULT", "USER_TRIM"]
Unsettled = Literal["NO_MAKE_MODEL", "UNKNOWN_MODEL", "PROPOSED", "UNRESOLVED"]

# Questions about a car: an answer that does not settle the car is reported as not understood (FR-031).
CAR_QUESTIONS = frozenset({"CAR_IDENTITY", "USED_AGE", "TRIM", "GEARBOX", "UNKNOWN_MODEL"})
# Asked again until answered (no other way to settle the car); the age of a used car is asked once and then
# offered as generation options to confirm, never guessed.
REASK = frozenset({"CAR_IDENTITY", "UNKNOWN_MODEL", "GEARBOX"})
LEVELS: tuple[Level, ...] = ("BASE", "MID", "TOP")


def settled(car: CaseCar) -> tuple[bool, Unsettled | None]:
    if not (car.make and car.model):
        return False, "NO_MAKE_MODEL"
    if car.resolution == "UNKNOWN_MODEL":
        return False, "UNKNOWN_MODEL"
    if car.resolution in ("CONFIRMED", "AUTO_OK") and car.variant_id:
        return True, None
    if car.resolution == "PROPOSED":
        return False, "PROPOSED"
    return False, "UNRESOLVED"


def _identity(c: CaseCar | None) -> tuple[object, ...]:
    if c is None:
        return ()
    k = c.constraints
    return (c.make, c.model, c.year, c.age_years, c.condition, k.generation_hint, k.fuel_hint, k.body_hint,
            k.trim_hint, k.gearbox_hint, k.drive_hint, k.url)  # fmt: skip


def answer_settles(kind: str, before: CaseCar | None, after: CaseCar | None, request: str) -> bool:
    """Did the message answer a car question (or a variant proposal) for this car?"""
    if after is None:
        return True  # the car was removed
    if kind == "CONFIRM_VARIANTS":
        return request in ("confirm_yes", "confirm_no", "choose_for_me") or _identity(before) != _identity(after)
    if kind in ("CAR_IDENTITY", "UNKNOWN_MODEL"):
        changed = before is None or (before.make, before.model) != (after.make, after.model)
        return bool(after.make and after.model) and changed
    if kind == "USED_AGE":
        return after.year is not None or after.age_years is not None
    if kind in ("TRIM", "GEARBOX"):
        return request == "choose_for_me" or _identity(before) != _identity(after)
    return True


def level_in_range(position: int, size: int) -> Level:
    """Level of a version from its position in the price-ordered range of the model (0 = cheapest)."""
    if size <= 1 or position <= 0:
        return "BASE"
    if position >= size - 1:
        return "TOP"
    return "MID"


def level_for(named_levels: Sequence[Level | None]) -> tuple[Level, LevelSource]:
    """The common level: the level of the first version the user named, otherwise BASE."""
    for lv in named_levels:
        if lv in LEVELS:
            return lv, "USER_TRIM"
    return "BASE", "DEFAULT"


def closest_models(name: str, known: Iterable[str], scorer: Callable[[str, str], float], *, limit: int = 3,
                   cutoff: float = 55.0) -> list[str]:  # fmt: skip
    scored = sorted(((scorer(name.lower(), k.lower()), k) for k in set(known)), key=lambda x: (-x[0], x[1]))
    return [k for s, k in scored if s >= cutoff][:limit]
