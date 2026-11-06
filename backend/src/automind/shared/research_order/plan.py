"""Case-driven research planner (FR-013, FR-014, FR-019..FR-021; research R8). Pure.

The case file (persona, criteria, condition) decides which areas are needed; cached areas that are
still fresh are skipped; each area has a minimum-evidence rule; gap rounds are bounded by depth.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal

Area = Literal[
    "specs", "engineering", "measured", "price", "maintenance", "reviews", "reliability", "manufacturer", "used_issues",
    "used_price", "depreciation", "incentives",
]  # fmt: skip
AREAS: tuple[Area, ...] = (
    "specs", "engineering", "measured", "price", "maintenance", "reviews", "reliability", "manufacturer", "used_issues",
    "used_price", "depreciation", "incentives",
)  # fmt: skip
MARKET_AREAS = ("incentives",)  # one job per market, not per car (spec 006 US5)
BRAND_AREAS = ("manufacturer",)  # pages about the make (warranty, network, results), not about one version
# spec 008 FR-023/FR-027: a used car is costed from its used price and its warranty status (the brand's terms)
USED_AREAS: tuple[str, ...] = ("used_issues", "used_price", "manufacturer")

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
    "incentives": 30,  # spec 006 FR-016: subsidies and deductions for the market, with dates
}
ROUNDS: dict[str, int] = {"QUICK": 0, "STANDARD": 1, "DEEP": 2}
RETRY_UNMET_HOURS = 12  # an area that missed its evidence minimum is tried again after this, not after months
# spec 010 FR-022: an area below its minimum whose research never tried the registry's sources with the escalation
# to the other European markets (or tried them longer ago than this) gets that round in the first research of a
# turn, whatever the retry window says: "no data" is shown only after the registry's sources were tried
REGISTRY_RETRY_DAYS = 7
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
    electrified: bool = False  # BEV, PHEV or EREV: the market's incentives matter (spec 006 US5)


@dataclass(frozen=True)
class Job:
    car_key: str
    variant_id: str
    area: str
    round: int = 0
    fresh: bool = False  # the user asked to search again: skip the search cache, wider queries
    escalate: bool = False  # round 0 also queries the registry's sources of the other markets (spec 010 FR-022)


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
    """Accepted evidence for an area: one source (domain), its type, and how many items it gave. `unverified`: the
    source is a registry candidate (spec 011 FR-022): it counts as half an independent source."""

    domain: str
    source_type: str
    items: int = 1
    unverified: bool = False


def areas_for(persona: str, criteria: Iterable[str], condition: str, budget_used: bool = False) -> set[str]:
    out = {"specs"} | PERSONA_AREAS.get(persona, PERSONA_AREAS["UNKNOWN"])
    for c in criteria:
        out |= CRITERION_AREAS.get(c, set())
    if condition == "USED":
        out |= set(USED_AREAS)
    if budget_used:  # a budget check may need used prices (spec 003 FR-022): price and editorial ranges
        out |= {"price", "used_price"}
    return out


def is_fresh(area: str, last_done: datetime | None, now: datetime) -> bool:
    return last_done is not None and now - last_done <= timedelta(days=FRESHNESS_DAYS[area])


def registry_tried(at: datetime | None, now: datetime, days: int = REGISTRY_RETRY_DAYS) -> bool:
    """The registry's sources (with the escalation) were tried for an area within the window."""
    return at is not None and now - at < timedelta(days=days)


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
    registry_done: Mapping[str, Mapping[str, datetime]] | None = None,
    registry_days: int = REGISTRY_RETRY_DAYS,
) -> ResearchPlan:
    """`force`: variant_id -> areas to research again although cached (the user asked to find missing data).
    `registry_done`: variant_id -> area -> when its research last tried the registry's sources with the escalation
    to the other markets; an unmet area without that (within `registry_days`) is retried now, escalated."""
    crit = list(criteria)
    jobs: list[Job] = []
    warnings: list[Warning] = []
    for car in cars:
        done = last_done.get(car.variant_id, {})
        for area in AREAS:  # stable order
            wanted = areas_for(persona, crit, car.condition, budget_used)
            forced = area in (force or {}).get(car.variant_id, set())
            short = area in (unmet or {}).get(car.variant_id, set())
            escalate = (
                short
                and not forced
                and area not in MARKET_AREAS
                and not registry_tried((registry_done or {}).get(car.variant_id, {}).get(area), now, registry_days)
            )
            retry = short and (done.get(area) is None or now - done[area] >= timedelta(hours=RETRY_UNMET_HOURS))
            again = forced or retry or escalate or not is_fresh(area, done.get(area), now)
            if (area in wanted or forced) and again:
                jobs.append(Job(car.key, car.variant_id, area, fresh=forced, escalate=escalate))
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
    jobs += _market_jobs(cars, jobs, last_done, now)
    return ResearchPlan(jobs=jobs, rounds=ROUNDS[depth], warnings=warnings)


def _market_jobs(cars: list[CarToPlan], jobs: list[Job], last_done: Mapping[str, Mapping[str, datetime]],
                 now: datetime) -> list[Job]:  # fmt: skip
    """The incentives of the market, once, on the first electrified car, when stale (last_done carries the
    market's date for every car)."""
    if any(j.area in MARKET_AREAS for j in jobs):
        return []
    car = next((c for c in cars if c.electrified), None)
    if car is None or is_fresh("incentives", last_done.get(car.variant_id, {}).get("incentives"), now):
        return []
    return [Job(car.key, car.variant_id, "incentives")]


def plan_key(p: ResearchPlan) -> str:
    """Stable identity of a plan (which car × area jobs), used to remember a declined research offer."""
    return "|".join(sorted(f"{j.variant_id}:{j.area}" for j in p.jobs))


MIN_PRICE_DOMAINS = 3  # a brand site that blocks readers must not leave a well-known price 'missing'


UNVERIFIED_WEIGHT = 0.5  # spec 011 FR-022 (010 T059): a candidate source is half an independent source


def _weight(hits: list[SourceHit], keep: Callable[[SourceHit], bool] = lambda h: True) -> float:
    """Independent sources (domains) with accepted items: 1 each, `UNVERIFIED_WEIGHT` for a domain whose every hit
    comes from a registry candidate (one verified hit makes the domain verified)."""
    verified: dict[str, bool] = {}
    for h in hits:
        if h.items > 0 and keep(h):
            verified[h.domain] = verified.get(h.domain, False) or not h.unverified
    return sum(1.0 if v else UNVERIFIED_WEIGHT for v in verified.values())


def _has_type(hits: list[SourceHit], source_type: str) -> bool:
    """A verified source of this type: a candidate brand site or lab alone is not the official word."""
    return _weight(hits, lambda h: h.source_type == source_type) >= 1


def _has_manufacturer(hits: list[SourceHit]) -> bool:
    return _has_type(hits, "MANUFACTURER")


def minimum_met(area: str, hits: list[SourceHit]) -> bool:
    """Section minimums (FR-019, constitution XI). Counts are weighted: a registry candidate counts half."""
    domains = _weight(hits)
    non_mfr = _weight(hits, lambda h: h.source_type != "MANUFACTURER")
    if area in ("specs", "engineering"):
        return (_has_manufacturer(hits) and non_mfr >= 1) or non_mfr >= 2
    if area == "maintenance":
        return _has_manufacturer(hits) or domains >= 2
    if area == "reviews":
        return sum(h.items for h in hits) >= 5 and domains >= 2
    if area in ("reliability", "used_issues", "manufacturer"):
        return domains >= 2
    if area in ("used_price", "depreciation"):
        return domains >= 1  # one editorial range for the model years; otherwise the labelled estimate
    if area == "price":  # the brand's own price list, or the same list price quoted by 3+ independent sites
        return _has_manufacturer(hits) or domains >= MIN_PRICE_DOMAINS
    if area == "measured":
        return _has_type(hits, "INSTRUMENTED_TEST")
    if area == "incentives":  # one official or press source with a dated programme
        return domains >= 1
    raise ValueError(f"unknown area {area!r}")


# Inputs the energy model needs (spec 006 FR-009): without them a plug-in or electric car's energy cost cannot be
# computed, so the specs area is not met and a deeper round looks for them before "cannot be computed".
ENERGY_INPUTS: dict[str, tuple[tuple[str, ...], ...]] = {  # every group needs at least one attribute
    "PHEV": (
        ("consumption_cs",),
        ("consumption_ev", "battery_kwh", "consumption_ev_cltc"),
        ("range_wltp", "range_real", "range_cltc"),
    ),
    "EREV": (
        ("consumption_cs",),
        ("consumption_ev", "battery_kwh", "consumption_ev_cltc"),
        ("range_wltp", "range_real", "range_cltc"),
    ),
    "BEV": (("consumption", "consumption_ev", "consumption_ev_real", "consumption_ev_plug", "consumption_ev_cltc"),),
}


def energy_inputs_missing(powertrain: str | None, have: set[str]) -> list[str]:
    """The first attribute of each group the energy model needs and the car does not have yet."""
    groups = ENERGY_INPUTS.get((powertrain or "").upper(), ())
    return [g[0] for g in groups if not any(a in have for a in g)]


# Spec 009 FR-009: Europe is one market (no country preferred); prices come from European markets only, other kinds
# of data may also come from the best source outside Europe. Codes are the registry's markets (EN = UK and Ireland,
# DE = Germany, Austria and Switzerland, FR = France and Belgium; ANY = Europe-wide sources).
EUROPE: tuple[str, ...] = ("ES", "EN", "DE", "FR", "IT", "PT", "NL", "SE", "DK", "NO", "FI", "PL", "CZ", "ANY")
OUTSIDE_EUROPE: tuple[str, ...] = ("US", "JP", "RU", "CN", "KR", "AU", "CA")
PRICE_AREAS: tuple[str, ...] = ("price", "used_price", "depreciation")


def registry_markets(area: str, searched: Iterable[str], round_: int) -> list[str]:
    """Markets whose registry sources get `site:` queries in a round (spec 009 FR-009, gap rounds FR-020).

    Round 0 stays on the markets the area searches (and Europe-wide sources). A follow-up round is the escalation
    for an area still below its minimum: the registry sources of the other European markets, then, for anything but
    prices, the markets outside Europe. Market-level areas (incentives) are about the user's own market: none."""
    if area in MARKET_AREAS:
        return []
    own = list(dict.fromkeys([*searched, "ANY"]))
    if round_ == 0:
        return own
    other = [m for m in EUROPE if m not in own]
    if area not in PRICE_AREAS:
        other += [m for m in OUTSIDE_EUROPE if m not in own]
    return other


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
