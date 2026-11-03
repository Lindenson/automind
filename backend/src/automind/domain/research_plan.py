"""Case-driven research planner (FR-013, FR-014, FR-019..FR-021; research R8). Pure.

The case file (persona, criteria, condition) decides which areas are needed; cached areas that are
still fresh are skipped; each area has a minimum-evidence rule; gap rounds are bounded by depth.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal

Area = Literal[
    "specs", "engineering", "measured", "price", "maintenance", "reviews", "reliability", "manufacturer", "used_issues",
    "used_price", "depreciation",
]  # fmt: skip
AREAS: tuple[Area, ...] = (
    "specs", "engineering", "measured", "price", "maintenance", "reviews", "reliability", "manufacturer", "used_issues",
    "used_price", "depreciation",
)  # fmt: skip

FRESHNESS_DAYS: dict[str, int] = {
    "specs": 365,
    "engineering": 365,
    "measured": 365,
    "maintenance": 365,
    "reliability": 180,
    "used_issues": 180,
    "reviews": 180,
    "price": 30,
    "manufacturer": 30,
    "used_price": 30,
    "depreciation": 90,  # spec 004 FR-005: residual values after 3 and 5 years
}
ROUNDS: dict[str, int] = {"QUICK": 0, "STANDARD": 1, "DEEP": 2}
RETRY_UNMET_HOURS = 12  # an area that missed its evidence minimum is tried again after this, not after months
OLD_CAR_YEARS = 25

PERSONA_AREAS: dict[str, set[str]] = {
    "BUYER": {"specs", "price", "maintenance", "reliability", "reviews"},
    "PERFORMANCE": {"specs", "measured", "reviews"},
    "EXPERT": {"specs", "engineering", "manufacturer", "measured", "reliability"},
    "UNKNOWN": {"specs", "price", "maintenance", "reliability", "measured"},
}
# Context areas (spec 004 US2): researched alongside a car's other research, in DEEP research or by "find it",
# never on their own for a car whose data is otherwise fresh (no surprise cost for cached reports).
ENRICH_AREAS: dict[str, set[Area]] = {
    "BUYER": {"depreciation", "manufacturer"},
    "UNKNOWN": {"depreciation", "manufacturer"},
    "EXPERT": {"depreciation"},
    "PERFORMANCE": set(),
}
CRITERION_AREAS: dict[str, set[str]] = {
    "reliability": {"reliability"},
    "ownership_cost": {"maintenance", "specs"},
    "purchase_price": {"price"},
    "practicality": {"specs"},
    "comfort": {"reviews"},
    "performance": {"specs", "measured"},
    "driving_fun": {"specs", "reviews"},
    "traction_all_weather": {"specs", "reviews"},
    "offroad_mountain": {"specs"},
    "efficiency": {"specs"},
    "safety": {"specs"},
    "status": {"price", "manufacturer"},
    "engineering": {"engineering", "manufacturer"},
}


@dataclass(frozen=True)
class CarToPlan:
    key: str
    variant_id: str
    condition: str
    age_years: int | None = None
    sold_in_es: bool | None = None  # None = unknown


@dataclass(frozen=True)
class Job:
    car_key: str
    variant_id: str
    area: str
    round: int = 0
    fresh: bool = False  # the user asked to search again: skip the search cache, wider queries


@dataclass(frozen=True)
class Warning:
    kind: Literal["OLD_CAR", "NOT_SOLD_IN_ES"]
    car_key: str


@dataclass(frozen=True)
class ResearchPlan:
    jobs: list[Job]
    rounds: int
    warnings: list[Warning] = field(default_factory=list)


@dataclass(frozen=True)
class SourceHit:
    """Accepted evidence for an area: one source (domain), its type, and how many items it gave."""

    domain: str
    source_type: str
    items: int = 1


def areas_for(persona: str, criteria: Iterable[str], condition: str, budget_used: bool = False) -> set[str]:
    out = {"specs"} | PERSONA_AREAS.get(persona, PERSONA_AREAS["UNKNOWN"])
    for c in criteria:
        out |= CRITERION_AREAS.get(c, set())
    if condition == "USED":
        out.add("used_issues")
    if budget_used:  # a budget check may need used prices (spec 003 FR-022): price and editorial ranges
        out |= {"price", "used_price"}
    return out


def is_fresh(area: str, last_done: datetime | None, now: datetime) -> bool:
    return last_done is not None and now - last_done <= timedelta(days=FRESHNESS_DAYS[area])


def plan(
    cars: list[CarToPlan],
    *,
    persona: str,
    criteria: Iterable[str],
    depth: str,
    last_done: Mapping[str, Mapping[str, datetime]],
    now: datetime,
    budget_used: bool = False,
    force: Mapping[str, set[str]] | None = None,
    unmet: Mapping[str, set[str]] | None = None,
) -> ResearchPlan:
    """`force`: variant_id -> areas to research again although cached (the user asked to find missing data)."""
    crit = list(criteria)
    jobs: list[Job] = []
    warnings: list[Warning] = []
    for car in cars:
        done = last_done.get(car.variant_id, {})
        for area in AREAS:  # stable order
            wanted = areas_for(persona, crit, car.condition, budget_used)
            forced = area in (force or {}).get(car.variant_id, set())
            retry = area in (unmet or {}).get(car.variant_id, set()) and (
                done.get(area) is None or now - done[area] >= timedelta(hours=RETRY_UNMET_HOURS)
            )
            if (area in wanted or forced) and (forced or retry or not is_fresh(area, done.get(area), now)):
                jobs.append(Job(car.key, car.variant_id, area, fresh=forced))
        # only alongside new or stale research of this car: not for "find it" or a retry of a missed minimum
        has_jobs = any(j.car_key == car.key and not j.fresh and j.area not in (unmet or {}).get(car.variant_id, set())
                       for j in jobs)  # fmt: skip
        for area in sorted(ENRICH_AREAS.get(persona, set()) - {j.area for j in jobs if j.car_key == car.key}):
            forced_car = bool((force or {}).get(car.variant_id))  # "find it": only the areas asked for
            if not forced_car and (has_jobs or depth == "DEEP") and not is_fresh(area, done.get(area), now):
                jobs.append(Job(car.key, car.variant_id, area))
        if car.age_years is not None and car.age_years > OLD_CAR_YEARS:
            warnings.append(Warning("OLD_CAR", car.key))
        if car.sold_in_es is False:
            warnings.append(Warning("NOT_SOLD_IN_ES", car.key))
    return ResearchPlan(jobs=jobs, rounds=ROUNDS[depth], warnings=warnings)


def plan_key(p: ResearchPlan) -> str:
    """Stable identity of a plan (which car × area jobs), used to remember a declined research offer."""
    return "|".join(sorted(f"{j.variant_id}:{j.area}" for j in p.jobs))


MIN_PRICE_DOMAINS = 3  # a brand site that blocks readers must not leave a well-known price 'missing'


def _independent(hits: list[SourceHit]) -> set[str]:
    return {h.domain for h in hits if h.items > 0}


def _has_manufacturer(hits: list[SourceHit]) -> bool:
    return any(h.source_type == "MANUFACTURER" and h.items > 0 for h in hits)


def minimum_met(area: str, hits: list[SourceHit]) -> bool:
    """Section minimums (FR-019, constitution XI)."""
    domains = _independent(hits)
    non_mfr = {h.domain for h in hits if h.items > 0 and h.source_type != "MANUFACTURER"}
    if area in ("specs", "engineering"):
        return (_has_manufacturer(hits) and len(non_mfr) >= 1) or len(non_mfr) >= 2
    if area == "maintenance":
        return _has_manufacturer(hits) or len(domains) >= 2
    if area == "reviews":
        return sum(h.items for h in hits) >= 5 and len(domains) >= 2
    if area in ("reliability", "used_issues", "manufacturer"):
        return len(domains) >= 2
    if area in ("used_price", "depreciation"):
        return len(domains) >= 1  # one editorial range for the model years; otherwise the labelled estimate
    if area == "price":  # the brand's own price list, or the same list price quoted by 3+ independent sites
        return _has_manufacturer(hits) or len(domains) >= MIN_PRICE_DOMAINS
    if area == "measured":
        return any(h.source_type == "INSTRUMENTED_TEST" and h.items > 0 for h in hits)
    raise ValueError(f"unknown area {area!r}")


def gaps(p: ResearchPlan, met: Mapping[tuple[str, str], bool], round_done: int) -> list[Job]:
    """Follow-up jobs for areas below their minimum, if the depth allows another round (FR-020)."""
    if round_done >= p.rounds:
        return []
    seen: set[tuple[str, str]] = set()
    out: list[Job] = []
    for j in p.jobs:
        k = (j.car_key, j.area)
        if k not in seen and not met.get(k, False):
            seen.add(k)
            out.append(Job(j.car_key, j.variant_id, j.area, round_done + 1, j.fresh))
    return out
