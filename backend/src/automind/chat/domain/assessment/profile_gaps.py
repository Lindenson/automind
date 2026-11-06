"""Which unknowns about the user would change the answer? (spec 004 FR-018; research R9). Pure.

Asked at most once, at most 3 in one round, before research, and only when the answer matters for these cars:
- KM_PER_YEAR: an electrified car (hybrid, plug-in, electric) against a combustion one — their running costs
  diverge with mileage — and the user has not said how much they drive;
- FAMILY_SIZE: an everyday buyer comparing cars of different size classes without saying who travels.
Nothing is asked when the profile is clear or the answer would not change the comparison.
"""

from __future__ import annotations

from collections.abc import Sequence

from automind.chat.domain.case.casefile import CaseFile, QuestionKind

ELECTRIFIED = {"HEV", "PHEV", "BEV"}
MAX_PROFILE_QUESTIONS = 2


def questions(case: CaseFile, powertrains: Sequence[str | None], classes: Sequence[str | None]) -> list[QuestionKind]:
    out: list[QuestionKind] = []
    pts = {p for p in powertrains if p}
    if (pts & ELECTRIFIED) and (pts - ELECTRIFIED) and not case.annual_km_stated and "KM_PER_YEAR" not in case.asked:
        out.append("KM_PER_YEAR")
    sizes = {c for c in classes if c}
    if (
        case.persona in ("BUYER", "UNKNOWN") and len(sizes) > 1 and case.needs.passengers is None
        and case.profile.family is None and "FAMILY_SIZE" not in case.asked
    ):  # fmt: skip
        out.append("FAMILY_SIZE")
    return out[:MAX_PROFILE_QUESTIONS]
