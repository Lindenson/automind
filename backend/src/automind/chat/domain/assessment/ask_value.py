"""Questions by value (spec 007 FR-006; research R5). Pure.

A profile field the user has not said (or that is only assumed) is asked only when its plausible values change the
answer: the comparison is scored again with each probe value, and the field is asked when the winner or the tie
changes. At most one field, the one that changes the outcome most often. Nothing is asked otherwise: the report
then shows the assumption.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from automind.chat.domain.case.casefile import CaseFile, QuestionKind

Outcome = tuple[str | None, bool]  # (winner car id, tie)

# question kind → (case field, basis key)
FIELDS: dict[str, tuple[str, str]] = {
    "KM_PER_YEAR": ("annual_km", "annual_km"),
    "OWNERSHIP_YEARS": ("ownership_years", "ownership_years"),
    "PERSONA": ("persona", "persona"),
    "HOME_CHARGING": ("profile.home_charging", "home_charging"),  # spec 006 R5
}
PROBE_KEYS = {"KM_PER_YEAR": "annual_km", "OWNERSHIP_YEARS": "ownership_years", "PERSONA": "persona",
              "HOME_CHARGING": "home_charging"}  # fmt: skip


def _get(case: CaseFile, field: str) -> Any:
    obj: Any = case
    for part in field.split("."):
        obj = getattr(obj, part)
    return obj


def _with(case: CaseFile, field: str, value: Any) -> CaseFile:
    if field.startswith("profile."):
        return case.model_copy(update={"profile": case.profile.model_copy(update={field[8:]: value})})
    return case.model_copy(update={field: value})


def _probe_values(kind: str, probes: Mapping[str, Sequence[Any]]) -> list[Any]:
    return list(probes.get(PROBE_KEYS[kind]) or [])


def changes(case: CaseFile, kind: str, outcome: Callable[[CaseFile], Outcome],
            probes: Mapping[str, Sequence[Any]]) -> int:  # fmt: skip
    """How many probe values give another winner or tie than the case as it is."""
    field, _ = FIELDS[kind]
    base = outcome(case)
    n = 0
    for v in _probe_values(kind, probes):
        if _get(case, field) == v:
            continue
        if outcome(_with(case, field, v)) != base:
            n += 1
    return n


def _from_users_words(case: CaseFile, key: str) -> bool:
    """Inferred from words the user wrote ("для семейной покупки" → BUYER): asking again reads as not listening."""
    return case.basis.get(key) == "INFERRED" and bool(case.profile.evidence.get(key))


def questions(case: CaseFile, outcome: Callable[[CaseFile], Outcome], probes: Mapping[str, Sequence[Any]],
              kinds: Sequence[str] = ("PERSONA", "HOME_CHARGING", "KM_PER_YEAR", "OWNERSHIP_YEARS"),
              ) -> list[QuestionKind]:  # fmt: skip
    """At most one question: the unsaid field whose plausible values change the outcome most often."""
    best: tuple[int, int, str] | None = None
    for order, kind in enumerate(kinds):
        _, key = FIELDS[kind]
        if case.basis.get(key, "ASSUMED") == "STATED" or kind in case.asked or _from_users_words(case, key):
            continue
        n = changes(case, kind, outcome, probes)
        if n and (best is None or n > best[0]):
            best = (n, -order, kind)
    return [best[2]] if best else []  # type: ignore[list-item]


# basis keys of the profile fields that move the weights (profile_rules.yaml), in the order they are confirmed
INFERRED_FIELDS = ("family", "driving_style", "usage", "region")


def inferred_flip(case: CaseFile, outcome: Callable[[CaseFile], Outcome]) -> tuple[str, Outcome] | None:
    """An INFERRED field (a guess from the user's words, not confirmed) that decides the winner or the tie
    (spec 007 J, T077): the same data scored as if the field were unknown gives another outcome. Returns the
    first such field and that other outcome; the report then shows the assumption and asks to confirm it."""
    base = outcome(case)
    for key in INFERRED_FIELDS:
        if case.basis.get(key) != "INFERRED":
            continue
        other = outcome(case.model_copy(update={"basis": {**case.basis, key: "ASSUMED"}}))
        if other != base:
            return key, other
    return None
