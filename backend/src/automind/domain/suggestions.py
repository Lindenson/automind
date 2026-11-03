"""Next-step suggestions after a report (spec 004 FR-020; research R10). Pure and deterministic.

Built from the verdict, the insights and the gaps; the orchestration layer phrases them in the user's
language. A suggestion is either a message the hub understands ("why is X ahead?") or a "find it" request.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from .insights import InsightSet
from .verdict import Verdict

Kind = Literal["WHY_AHEAD", "WHAT_IF_USED", "COMPARE_RELIABILITY", "CHEAPER_ALTERNATIVE", "FIND_MISSING", "TIE_BREAK"]
MAX_SUGGESTIONS = 4


@dataclass(frozen=True)
class Suggestion:
    kind: Kind
    car_id: str | None = None  # the car the suggestion is about
    focus_cars: tuple[str, ...] = ()  # case car keys (FIND_MISSING)
    areas: tuple[str, ...] = ()
    args: Mapping[str, str] = field(default_factory=dict)


def build(
    v: Verdict,
    s: InsightSet,
    *,
    all_new: bool,
    gaps_by_car: Mapping[str, Sequence[str]],  # case car key -> areas missing
) -> list[Suggestion]:
    out: list[Suggestion] = []
    if v.pick_car_id:
        out.append(Suggestion("WHY_AHEAD", v.pick_car_id))
    elif v.tie and v.tied_cars:
        out.append(Suggestion("TIE_BREAK", v.tied_cars[0]))
    missing = {k: tuple(a) for k, a in gaps_by_car.items() if a}
    if missing:
        areas = tuple(sorted({area for car_areas in missing.values() for area in car_areas}))
        out.append(Suggestion("FIND_MISSING", focus_cars=tuple(sorted(missing)), areas=areas))
    if "reliability_score" not in v.reasons:
        out.append(Suggestion("COMPARE_RELIABILITY"))
    if all_new:
        out.append(Suggestion("WHAT_IF_USED"))
    target = v.pick_car_id or (v.tied_cars[0] if v.tied_cars else None)
    if target is None and not s.single and s.insights:
        target = s.insights[0].cars[0].car_id
    out.append(Suggestion("CHEAPER_ALTERNATIVE", target))
    return out[:MAX_SUGGESTIONS]
