"""Criteria dictionary and deterministic scoring (FR-025..FR-029; research R7).

Each criterion maps validated data to a 0–100 index with named inputs. A criterion without data is
"insufficient", never guessed. A car whose covered weight is below the minimum is not ranked.
Wishes add points to persona default weights; weights are normalized to 100.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from typing import Any

from . import weights
from .casefile import CRITERION_KEYS, CaseFile
from .metrics import CarFacts, ReliabilitySummary, ReviewSummary, lin, metrics

__all__ = ["CriteriaModel", "CriteriaScore", "ReliabilitySummary", "ReviewSummary", "score", "weights_for"]


@dataclass(frozen=True)
class Criterion:
    key: str
    label: str
    definition: str
    inputs: list[str]
    scale: dict[str, Any]


@dataclass(frozen=True)
class CriteriaModel:
    version: int
    criteria: dict[str, Criterion]
    personas: dict[str, dict[str, float]]
    strength_points: dict[str, float]
    min_coverage: float
    rules: weights.ProfileRules | None = None  # config/profile_rules.yaml (spec 007)

    @classmethod
    def from_config(cls, d: Mapping[str, Any], rules: Mapping[str, Any] | None = None) -> CriteriaModel:
        crit = {
            k: Criterion(k, v["label"], v["definition"], list(v.get("inputs", [])), dict(v.get("scale", {})))
            for k, v in d["criteria"].items()
        }
        missing = set(CRITERION_KEYS) - set(crit)
        if missing:
            raise ValueError(f"criteria.yaml lacks: {sorted(missing)}")
        return cls(
            version=int(d["criteria_version"]),
            criteria=crit,
            personas={p: {k: float(w) for k, w in ws.items()} for p, ws in d["personas"].items()},
            strength_points={k: float(v) for k, v in d["strength_points"].items()},
            min_coverage=float(d["min_coverage"]),
            rules=weights.ProfileRules.from_config(rules) if rules is not None else None,
        )


def _normalize(raw: Mapping[str, float]) -> dict[str, float]:
    total = sum(v for v in raw.values() if v > 0)
    return {k: round(v * 100 / total, 4) for k, v in raw.items() if v > 0} if total else {}


def weight_breakdown(case: CaseFile, model: CriteriaModel) -> weights.WeightBreakdown:
    """Persona + profile rules + wishes + the user's adjustments, each with its reason (spec 007 FR-008)."""
    return weights.breakdown(case, model.personas, model.strength_points, model.rules)


def automatic_weights(case: CaseFile, model: CriteriaModel) -> dict[str, float]:
    return weights.automatic(case, model.personas, model.strength_points, model.rules)[0]


def set_manual_weights(case: CaseFile, raw: Mapping[str, float], model: CriteriaModel) -> CaseFile:
    """The user set weights in the panel (FR-026; spec 007 FR-010): kept as adjustments on top of the automatic
    weights, so a later persona or profile change still moves the rest; a 0 excludes the criterion."""
    unknown = [k for k in raw if k not in CRITERION_KEYS]
    if unknown:
        raise ValueError(f"unknown criteria: {', '.join(unknown)}")
    if any(v < 0 for v in raw.values()):
        raise ValueError("weights must be ≥ 0")
    c = case.model_copy(deep=True)
    c.weights, c.weights_overridden = {}, False  # the old absolute form is replaced
    auto = automatic_weights(c, model)
    c.weight_adjustments = weights.manual_adjustments(c, {k: v for k, v in raw.items() if v > 0}, auto)
    c.weights_excluded = sorted(k for k, v in raw.items() if v == 0 and auto.get(k, 0) > 0)
    for k in c.weights_excluded:
        c.weight_adjustments.pop(k, None)
    return c


def reset_weights(case: CaseFile) -> CaseFile:
    c = case.model_copy(deep=True)
    c.weights, c.weights_overridden, c.weight_adjustments, c.weights_excluded = {}, False, {}, []
    return c


def weights_for(case: CaseFile, model: CriteriaModel) -> dict[str, float]:
    """The final weights, normalized to 100 (FR-026; spec 007 FR-008)."""
    return weight_breakdown(case, model).final


@dataclass(frozen=True)
class Part:
    score: float | None
    weight: float
    inputs: list[str]
    insufficient: bool


@dataclass(frozen=True)
class CarScore:
    car_id: str
    label: str
    total: float | None
    coverage: float
    ranked: bool
    parts: dict[str, Part]


@dataclass(frozen=True)
class CriteriaScore:
    criteria_version: int
    cars: list[CarScore]
    winner_car_id: str | None
    weights: dict[str, float] = field(default_factory=dict)
    common: list[str] = field(default_factory=list)  # criteria every compared car has data for (the ranking basis)
    tie: bool = False  # the best totals are within TIE_MARGIN: no winner is declared


Result = tuple[float | None, list[str]]


def _avg(values: list[float | None]) -> float | None:
    vs = [v for v in values if v is not None]
    return round(sum(vs) / len(vs), 1) if vs else None


def _pair(sc: Mapping[str, Any], key: str) -> tuple[float, float]:
    lo, hi = sc[key]
    return float(lo), float(hi)


def _reliability(c: CarFacts, sc: Mapping[str, Any]) -> Result:
    r = c.reliability
    if r is None or not r.minimum_met:
        return None, ["reliability sources below minimum"]

    def capped(per: str, n: int, cap: str) -> float:
        return float(max(float(sc.get(cap, -1e9)), float(sc[per]) * n))

    s = (
        float(sc["base_none_found"])
        + capped("per_recurring", r.recurring, "recurring_cap")
        + capped("per_high", r.high, "high_cap")
        + capped("per_isolated", r.isolated, "isolated_cap")
    )
    inputs = [f"{r.recurring} recurring, {r.isolated} isolated issue(s), {r.high} severe"]
    if c.condition == "USED" and c.age_years is not None and c.age_years > sc["age_free_years"]:
        s += max(sc["age_max"], sc["per_year_over"] * (c.age_years - sc["age_free_years"]))
        inputs.append(f"age {c.age_years} years")
    return round(max(0.0, min(100.0, s)), 1), inputs


def _ownership(c: CarFacts, sc: Mapping[str, Any]) -> Result:
    if c.annual_cost_eur is None:
        return None, []
    return lin(c.annual_cost_eur, sc["lo"], sc["hi"]), [f"ownership cost {c.annual_cost_eur:.0f} EUR/year"]


def _price(c: CarFacts, sc: Mapping[str, Any]) -> Result:
    if c.price_eur is None:
        return None, []
    return lin(c.price_eur, sc["lo"], sc["hi"]), [f"official price {c.price_eur:.0f} EUR"]


def _practicality(c: CarFacts, sc: Mapping[str, Any]) -> Result:
    parts = [
        (lin(c.boot_l, *_pair(sc, "boot")), f"boot {c.boot_l:.0f} L" if c.boot_l else None),
        (lin(c.seats, *_pair(sc, "seats")), f"{c.seats:.0f} seats" if c.seats else None),
        (lin(c.rear_legroom_mm, *_pair(sc, "rear_legroom")), "rear legroom" if c.rear_legroom_mm else None),
    ]
    if c.boot_l is None and c.seats is None:
        return None, []
    return _avg([p for p, _ in parts]), [i for _, i in parts if i]


def _balance(r: ReviewSummary | None, tags: list[str]) -> Result:
    if r is None or not r.minimum_met:
        return None, ["reviews below minimum"]
    pros = sum(r.recurring.get(t, (0, 0))[0] for t in tags)
    cons = sum(r.recurring.get(t, (0, 0))[1] for t in tags)
    if pros + cons == 0:
        return None, ["no recurring review points"]
    return round(100 * pros / (pros + cons), 1), [f"{pros} recurring pro / {cons} recurring con ({', '.join(tags)})"]


def _comfort(c: CarFacts, sc: Mapping[str, Any]) -> Result:
    return _balance(c.reviews, list(sc["tags"]))


def _performance(c: CarFacts, sc: Mapping[str, Any]) -> Result:
    m = metrics(c)
    if m["power_to_weight"] is None:
        return None, []
    inputs = [f"power-to-weight {m['power_to_weight']} kW/t"]
    if c.sim_0_100:
        inputs.append(f"0–100 {c.sim_0_100} s (simulated)")
    return _avg(
        [
            lin(c.sim_0_100, *_pair(sc, "sim_0_100")),
            lin(c.sim_400m, *_pair(sc, "sim_400m")),
            lin(m["power_to_weight"], *_pair(sc, "power_to_weight")),
        ]
    ), inputs


def _fun(c: CarFacts, sc: Mapping[str, Any]) -> Result:
    m = metrics(c)
    if m["power_to_weight"] is None:
        return None, []
    weighted = [
        (lin(m["power_to_weight"], *_pair(sc, "power_to_weight")), 0.4),
        (lin(c.mass_kg, *_pair(sc, "mass")), 0.2),
        (sc["drivetrain"].get(c.drivetrain or ""), 0.2),
        (_balance(c.reviews, ["handling"])[0], 0.2),
    ]
    avail = [(v, w) for v, w in weighted if v is not None]
    total = sum(w for _, w in avail)
    inputs = [f"power-to-weight {m['power_to_weight']} kW/t", f"weight {c.mass_kg:.0f} kg"]
    if c.drivetrain:
        inputs.append(f"drivetrain {c.drivetrain}")
    return round(sum(v * w for v, w in avail) / total, 1), inputs


def _traction(c: CarFacts, sc: Mapping[str, Any]) -> Result:
    base = sc["drivetrain"].get(c.drivetrain or "")
    if base is None:
        return None, []
    bonus = sc["low_range_bonus"] if c.low_range == "YES" else 0
    inputs = [f"drivetrain {c.drivetrain}"] + (["low range"] if bonus else [])
    return float(min(100, base + bonus)), inputs


def _offroad(c: CarFacts, sc: Mapping[str, Any]) -> Result:
    m = metrics(c)
    vals = {
        "ground clearance": lin(c.ground_clearance_mm, *_pair(sc, "ground_clearance")),
        "torque-to-weight": lin(m["torque_to_weight"], *_pair(sc, "torque_to_weight")),
        "low range": sc["low_range"].get(c.low_range or ""),
        "drivetrain": sc["drivetrain"].get(c.drivetrain or ""),
    }
    have = {k: v for k, v in vals.items() if v is not None}
    if len(have) < 2:
        return None, []
    return _avg(list(have.values())), sorted(have)


def _efficiency(c: CarFacts, sc: Mapping[str, Any]) -> Result:
    if not c.consumption:
        return None, []
    bev = c.powertrain == "BEV"
    unit = "kWh/100 km" if bev else "l/100 km"
    return lin(c.consumption, *_pair(sc, "bev" if bev else "ice")), [f"consumption {c.consumption} {unit}"]


def _safety(c: CarFacts, sc: Mapping[str, Any]) -> Result:
    if c.euro_ncap is None:
        return None, []
    return float(c.euro_ncap * sc["per_star"]), [f"Euro NCAP {c.euro_ncap:.0f} stars"]


def _status(c: CarFacts, sc: Mapping[str, Any]) -> Result:
    vals: list[tuple[float, str]] = []
    if c.price_eur is not None:
        p = lin(c.price_eur, *_pair(sc, "price"))
        assert p is not None
        vals.append((p, f"price class ({c.price_eur:.0f} EUR new)"))
    if c.vehicle_class in sc["class"]:
        vals.append((float(sc["class"][c.vehicle_class]), f"segment ({c.vehicle_class})"))
    brand = c.brand_positioning
    if brand is not None and brand in sc["brand"]:
        vals.append((float(sc["brand"][brand]), f"brand positioning ({brand.lower()})"))
    if len(vals) < 2:
        return None, [i for _, i in vals]
    s = sum(v for v, _ in vals) / len(vals)
    inputs = [i for _, i in vals]
    if c.condition == "USED" and c.age_years is not None and c.age_years > sc["age_free_years"]:
        s += max(sc["age_max"], sc["per_year_over"] * (c.age_years - sc["age_free_years"]))
        inputs.append(f"age {c.age_years} years")
    return round(max(0.0, s), 1), inputs


def _engineering(c: CarFacts, sc: Mapping[str, Any]) -> Result:
    m = metrics(c)
    vals = {
        "specific output": lin(m["specific_output"], *_pair(sc, "specific_output")),
        "torque-to-weight": lin(m["torque_to_weight"], *_pair(sc, "torque_to_weight")),
        "engineering data documented": (
            round(c.engineering_completeness * 100, 1) if c.engineering_completeness is not None else None
        ),
    }
    have = {k: v for k, v in vals.items() if v is not None}
    if len(have) < 2:
        return None, []
    return _avg(list(have.values())), sorted(have)


SCORERS: dict[str, Callable[[CarFacts, Mapping[str, Any]], Result]] = {
    "reliability": _reliability,
    "ownership_cost": _ownership,
    "purchase_price": _price,
    "practicality": _practicality,
    "comfort": _comfort,
    "performance": _performance,
    "driving_fun": _fun,
    "traction_all_weather": _traction,
    "offroad_mountain": _offroad,
    "efficiency": _efficiency,
    "safety": _safety,
    "status": _status,
    "engineering": _engineering,
}


def _car_score(c: CarFacts, weights: Mapping[str, float], model: CriteriaModel, ranking: bool) -> CarScore:
    parts: dict[str, Part] = {}
    for key, w in weights.items():
        s, inputs = SCORERS[key](c, model.criteria[key].scale)
        parts[key] = Part(score=s, weight=w, inputs=inputs, insufficient=s is None)
    total_w = sum(weights.values())
    covered = {k: p for k, p in parts.items() if p.score is not None}
    cw = sum(p.weight for p in covered.values())
    coverage = round(cw / total_w, 3) if total_w else 0.0
    total = round(sum(p.weight * (p.score or 0) for p in covered.values()) / cw, 1) if cw else None
    ranked = ranking and coverage >= model.min_coverage
    return CarScore(
        c.car_id, c.label, total if coverage >= model.min_coverage or not ranking else None, coverage, ranked, parts
    )


TIE_MARGIN = 3.0  # points: closer totals are reported as a tie, not as a win


# Euro NCAP protocol periods: stars are comparable only within one (reviewer 2026-11-03)
NCAP_PERIODS = ((2009, 2015), (2016, 2019), (2020, 2022), (2023, 2025), (2026, 2035))


def ncap_period(year: float | None) -> int | None:
    if year is None:
        return None
    return next((i for i, (a, b) in enumerate(NCAP_PERIODS) if a <= year <= b), None)


def ncap_comparable(cars: list[CarFacts]) -> bool:
    """Stars of the compared cars come from one protocol period; an unknown year is not assumed different."""
    periods = {ncap_period(c.euro_ncap_year) for c in cars if c.euro_ncap is not None and c.euro_ncap_year}
    return len(periods) <= 1


def score(cars: list[CarFacts], weights: Mapping[str, float], model: CriteriaModel) -> CriteriaScore:
    """Deterministic criteria scores. A single car is a profile: absolute scores, no ranking (FR-012).

    Ranking uses only the criteria every compared car has data for: a missing criterion must neither help
    a car (its weight would move to its strong points) nor hurt it. Close totals are a tie."""
    unknown = [k for k in weights if k not in SCORERS]
    if unknown:
        raise ValueError(f"unknown criteria: {unknown}")
    ranking = len(cars) > 1
    if ranking and not ncap_comparable(cars):  # 5★ of 2015 vs 5★ of 2024: safety is not ranked on stars
        cars = [replace(c, euro_ncap=None) for c in cars]
    scored = [_car_score(c, weights, model, ranking) for c in cars]
    if not ranking:
        return CriteriaScore(model.version, scored, None, dict(weights))
    common = [k for k in weights if all(sc.parts[k].score is not None for sc in scored)]
    total_w = sum(weights.values()) or 1.0
    cw = sum(weights[k] for k in common)
    enough = cw / total_w >= model.min_coverage
    rescored = [
        replace(
            sc,
            total=round(sum(weights[k] * (sc.parts[k].score or 0) for k in common) / cw, 1) if enough and cw else None,
            ranked=enough,
        )
        for sc in scored
    ]
    ranked = sorted((s for s in rescored if s.total is not None), key=lambda s: (-(s.total or 0), s.car_id))
    tie = len(ranked) > 1 and (ranked[0].total or 0) - (ranked[1].total or 0) < TIE_MARGIN
    winner = ranked[0].car_id if ranked and not tie else None
    return CriteriaScore(model.version, rescored, winner, dict(weights), common, tie)
