"""Questions by value (spec 007 FR-006; research R5). Pure.

A profile field the user has not said (or that is only assumed) is asked only when its plausible values change the
answer: the comparison is scored again with each probe value, and the field is asked when the winner or the tie
changes. At most one field, the one that changes the outcome most often. Nothing is asked otherwise: the report
then shows the assumption.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from .casefile import CaseFile, QuestionKind

Outcome = tuple[str | None, bool]  # (winner car id, tie)

# question kind → (case field, basis key)
FIELDS: dict[str, tuple[str, str]] = {
    "KM_PER_YEAR": ("annual_km", "annual_km"),
    "OWNERSHIP_YEARS": ("ownership_years", "ownership_years"),
    "PERSONA": ("persona", "persona"),
}
PROBE_KEYS = {"KM_PER_YEAR": "annual_km", "OWNERSHIP_YEARS": "ownership_years", "PERSONA": "persona"}


def _probe_values(kind: str, probes: Mapping[str, Sequence[Any]]) -> list[Any]:
    return list(probes.get(PROBE_KEYS[kind]) or [])


def changes(case: CaseFile, kind: str, outcome: Callable[[CaseFile], Outcome],
            probes: Mapping[str, Sequence[Any]]) -> int:  # fmt: skip
    """How many probe values give another winner or tie than the case as it is."""
    field, _ = FIELDS[kind]
    base = outcome(case)
    n = 0
    for v in _probe_values(kind, probes):
        if getattr(case, field) == v:
            continue
        if outcome(case.model_copy(update={field: v})) != base:
            n += 1
    return n


def questions(case: CaseFile, outcome: Callable[[CaseFile], Outcome], probes: Mapping[str, Sequence[Any]],
              kinds: Sequence[str] = ("PERSONA", "KM_PER_YEAR", "OWNERSHIP_YEARS")) -> list[QuestionKind]:  # fmt: skip
    """At most one question: the unsaid field whose plausible values change the outcome most often."""
    best: tuple[int, int, str] | None = None
    for order, kind in enumerate(kinds):
        _, key = FIELDS[kind]
        if case.basis.get(key, "ASSUMED") == "STATED" or kind in case.asked:
            continue
        n = changes(case, kind, outcome, probes)
        if n and (best is None or n > best[0]):
            best = (n, -order, kind)
    return [best[2]] if best else []  # type: ignore[list-item]
