"""Feasibility of the user's constraints (spec 003 FR-019..FR-023; research R11). Pure.

Budget, running-cost limit and usage needs are checked per car with deterministic rules; every number
carries its basis (SOURCED or ASSUMPTION) and sources. Used-car age ranges for a budget come from
editorial used-price ranges when found, otherwise from the configured depreciation curve (labelled
ASSUMPTION); when both exist and disagree both are shown and the editorial range decides.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

Verdict = Literal["FITS", "DOES_NOT_FIT", "USED_ONLY", "OTHER_CLASS", "UNKNOWN"]
Check = Literal["BUDGET", "RUNNING_COST", "USAGE_SPACE", "USAGE_POWER", "USAGE_RANGE"]
Basis = Literal["SOURCED", "ASSUMPTION"]


@dataclass(frozen=True)
class Fact:
    value: float
    basis: Basis = "SOURCED"
    sources: Sequence[str] = ()
    inputs: Sequence[str] = ()


@dataclass(frozen=True)
class UsedRange:
    year_from: int | None
    year_to: int | None
    min_eur: float
    max_eur: float
    source: str
    quoted_on: str | None = None


@dataclass(frozen=True)
class CarFacts:
    key: str
    label: str
    condition: str = "UNKNOWN"  # NEW | USED | UNKNOWN
    age_years: int | None = None
    vehicle_class: str | None = None
    price: Fact | None = None  # official new price, EUR
    tco_annual: Fact | None = None  # EUR per year
    seats: Fact | None = None
    boot_l: Fact | None = None
    power_kw: Fact | None = None
    mass_kg: Fact | None = None
    battery_kwh: Fact | None = None
    consumption: Fact | None = None  # kWh/100 km for BEV
    powertrain: str | None = None  # spec 006: only a BEV's range limits the daily distance
    range_wltp: Fact | None = None  # km, BEV
    used_ranges: Sequence[UsedRange] = ()


@dataclass(frozen=True)
class Needs:
    budget_eur: float | None = None  # already in EUR and as a total
    budget_amount: float | None = None  # as stated (converted by `budget_total`)
    budget_currency: str = "EUR"
    budget_kind: str = "TOTAL"  # TOTAL | MONTHLY
    intent: str = "UNKNOWN"  # NEW | USED | ANY | UNKNOWN
    running_month_eur: float | None = None
    passengers: int | None = None
    luggage: str = "MEDIUM"  # LOW | MEDIUM | HIGH
    mountains: bool = False
    towing_kg: int | None = None
    daily_km: int | None = None

    def any(self) -> bool:
        return any(
            (self.budget_eur, self.budget_amount, self.running_month_eur, self.passengers, self.mountains,
             self.towing_kg, self.daily_km)
        )  # fmt: skip


@dataclass(frozen=True)
class Num:
    label: str
    value: float | None
    unit: str
    basis: Basis = "SOURCED"
    sources: Sequence[str] = ()
    inputs: Sequence[str] = ()


@dataclass(frozen=True)
class UsedAge:
    from_years: int
    to_years: int
    basis: Literal["EDITORIAL", "ASSUMPTION"]


@dataclass(frozen=True)
class CheckResult:
    check: Check
    verdict: Verdict
    summary: str
    compared: list[Num] = field(default_factory=list)
    used_age: UsedAge | None = None
    missing: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CarFeasibility:
    car_key: str
    label: str
    checks: list[CheckResult]

    @property
    def problems(self) -> list[CheckResult]:
        return [c for c in self.checks if c.verdict != "FITS"]


def _eur(v: float) -> str:
    return f"€{v:,.0f}"


def budget_total(n: Needs, rules: Mapping[str, Any]) -> Num | None:
    if n.budget_eur is not None:
        return Num("your budget", n.budget_eur, "EUR")
    if n.budget_amount is None:
        return None
    rate = float((rules.get("currency_to_eur") or {}).get(n.budget_currency, 1.0))
    months = int(rules.get("monthly_budget_months", 48)) if n.budget_kind == "MONTHLY" else 1
    inputs = []
    if n.budget_currency != "EUR":
        inputs.append(f"1 {n.budget_currency} = {rate} EUR")
    if months > 1:
        inputs.append(f"{n.budget_amount:,.0f} per month × {months} months")
    basis: Basis = "ASSUMPTION" if inputs else "SOURCED"
    return Num("your budget", n.budget_amount * rate * months, "EUR", basis, (), tuple(inputs))


def share_left(rules: Mapping[str, Any], vehicle_class: str | None, age: float) -> float:
    curves = rules.get("depreciation") or {}
    curve = curves.get(vehicle_class or "") or curves.get("compact") or {0: 1.0}
    pts = sorted((float(k), float(v)) for k, v in curve.items())
    if age <= pts[0][0]:
        return pts[0][1]
    for (a0, v0), (a1, v1) in zip(pts, pts[1:], strict=False):
        if a0 <= age <= a1:
            return v0 + (v1 - v0) * (age - a0) / (a1 - a0)
    return pts[-1][1]


def _depreciation_age(price: float, budget: float, car: CarFacts, rules: Mapping[str, Any]) -> int | None:
    for age in range(1, int(rules.get("max_used_age_years", 20)) + 1):
        if price * share_left(rules, car.vehicle_class, age) <= budget:
            return age
    return None


def _editorial_ages(car: CarFacts, budget: float, year: int) -> tuple[int, int, UsedRange] | None:
    fits = [r for r in car.used_ranges if r.min_eur <= budget and (r.year_from or r.year_to)]
    if not fits:
        return None
    best = max(fits, key=lambda r: r.year_to or r.year_from or 0)  # the newest model years that fit
    newest = best.year_to or best.year_from or year
    oldest = best.year_from or newest
    return year - newest, year - oldest, best


def _budget(n: Needs, car: CarFacts, rules: Mapping[str, Any], year: int) -> CheckResult | None:
    b = budget_total(n, rules)
    if b is None or b.value is None:
        return None
    budget = float(b.value)
    if car.price is None and not car.used_ranges:
        return CheckResult("BUDGET", "UNKNOWN", "The official price was not found, so the budget could not be checked.",
                           [b], missing=["official price"])  # fmt: skip
    price_num = (Num("official price", car.price.value, "EUR", car.price.basis, car.price.sources)
                 if car.price else None)  # fmt: skip
    if car.condition == "USED" and car.age_years is not None and car.price is not None:
        est = car.price.value * share_left(rules, car.vehicle_class, car.age_years)
        why = f"official price {_eur(car.price.value)} × depreciation for {car.vehicle_class or 'compact'}"
        value = Num(f"estimated value at {car.age_years} years", round(est), "EUR", "ASSUMPTION", (), (why,))
        fits = est <= budget
        return CheckResult("BUDGET", "FITS" if fits else "DOES_NOT_FIT",
                           f"A {car.age_years}-year-old one is worth about {_eur(est)} (estimate); your budget is "
                           f"{_eur(budget)}.", [value, b])  # fmt: skip
    compared = [x for x in (price_num, b) if x is not None]
    if car.price is not None and car.price.value <= budget:
        return CheckResult("BUDGET", "FITS", f"New from {_eur(car.price.value)}, within your {_eur(budget)}.", compared)
    if n.intent == "NEW":
        new_price = _eur(car.price.value) if car.price else "more"
        return CheckResult(
            "BUDGET", "DOES_NOT_FIT", f"New it costs {new_price}; your budget is {_eur(budget)}.", compared
        )
    editorial = _editorial_ages(car, budget, year)
    dep_age = _depreciation_age(car.price.value, budget, car, rules) if car.price else None
    span = int(rules.get("used_age_span_years", 3))
    if dep_age is not None and car.price is not None:
        compared.append(Num(f"estimated value at {dep_age} years", round(car.price.value * share_left(
            rules, car.vehicle_class, dep_age)), "EUR", "ASSUMPTION", (),
            (f"depreciation curve for {car.vehicle_class or 'compact'} (assumption)",)))  # fmt: skip
    if editorial is not None:
        lo, hi, r = editorial
        compared.append(Num(f"used price {r.year_from or ''}–{r.year_to or ''}", r.min_eur, "EUR", "SOURCED",
                            (r.source,), (f"range {_eur(r.min_eur)}–{_eur(r.max_eur)}",)))  # fmt: skip
        return CheckResult("BUDGET", "USED_ONLY",
                           f"New is over your {_eur(budget)}; used ones about {lo}–{hi} years old are quoted from "
                           f"{_eur(r.min_eur)}.", compared, UsedAge(lo, hi, "EDITORIAL"))  # fmt: skip
    if dep_age is not None:
        return CheckResult("BUDGET", "USED_ONLY",
                           f"New is over your {_eur(budget)}; a used one about {dep_age}–{dep_age + span} years old "
                           "should fit (estimate from typical depreciation).", compared,
                           UsedAge(dep_age, dep_age + span, "ASSUMPTION"))  # fmt: skip
    return CheckResult("BUDGET", "DOES_NOT_FIT",
                       f"Even a car older than {int(rules.get('max_used_age_years', 20))} years is estimated above "
                       f"your {_eur(budget)}; a cheaper class of car would fit.", compared)  # fmt: skip


def _running(n: Needs, car: CarFacts) -> CheckResult | None:
    if n.running_month_eur is None:
        return None
    limit = Num("your monthly limit", n.running_month_eur, "EUR")
    if car.tco_annual is None:
        return CheckResult("RUNNING_COST", "UNKNOWN", "The running cost could not be computed.", [limit],
                           missing=["ownership cost"])  # fmt: skip
    month = car.tco_annual.value / 12
    num = Num("running cost per month", round(month), "EUR", car.tco_annual.basis, car.tco_annual.sources,
              car.tco_annual.inputs)  # fmt: skip
    fits = month <= n.running_month_eur
    return CheckResult("RUNNING_COST", "FITS" if fits else "DOES_NOT_FIT",
                       f"About {_eur(month)} a month to run (fuel, maintenance, tyres, tax); your limit is "
                       f"{_eur(n.running_month_eur)}.", [num, limit])  # fmt: skip


def _space(n: Needs, car: CarFacts, rules: Mapping[str, Any]) -> CheckResult | None:
    if not n.passengers:
        return None
    missing = [m for m, f in (("seats", car.seats), ("boot volume", car.boot_l)) if f is None]
    if car.seats is not None and car.seats.value < n.passengers:
        seats = Num("seats", car.seats.value, "", car.seats.basis, car.seats.sources)
        text = f"It has {int(car.seats.value)} seats for {n.passengers} people."
        return CheckResult("USAGE_SPACE", "DOES_NOT_FIT", text, [seats])
    if car.boot_l is None:
        return CheckResult("USAGE_SPACE", "UNKNOWN", "Seats or boot volume are not known.", missing=missing)
    per = float((rules.get("usage") or {}).get("boot_l_per_passenger", {}).get(n.luggage, 100))
    need = per * n.passengers
    boot = Num("boot", car.boot_l.value, "L", car.boot_l.basis, car.boot_l.sources)
    needed = Num(
        "needed for the luggage", need, "L", "ASSUMPTION", (), (f"{per:.0f} L per person ({n.luggage.lower()})",)
    )
    fits = car.boot_l.value >= need
    return CheckResult("USAGE_SPACE", "FITS" if fits else "DOES_NOT_FIT",
                       f"Boot {car.boot_l.value:.0f} L for {n.passengers} people with {n.luggage.lower()} luggage "
                       f"(about {need:.0f} L needed).", [boot, needed], missing=missing)  # fmt: skip


def _power(n: Needs, car: CarFacts, rules: Mapping[str, Any]) -> CheckResult | None:
    if not (n.mountains or n.towing_kg):
        return None
    if car.power_kw is None or car.mass_kg is None:
        missing = [m for m, f in (("power", car.power_kw), ("weight", car.mass_kg)) if f is None]
        return CheckResult("USAGE_POWER", "UNKNOWN", "Power or weight is not known.", missing=missing)
    th = (rules.get("usage") or {}).get("min_kw_per_t", {})
    out: list[Num] = []
    ok = True
    if n.mountains:
        kwt = car.power_kw.value / (car.mass_kg.value / 1000)
        need = float(th.get("mountains", 60))
        out += [
            Num("power-to-weight", round(kwt), "kW/t"),
            Num("comfortable in mountains from", need, "kW/t", "ASSUMPTION"),
        ]
        ok = ok and kwt >= need
    if n.towing_kg:
        kwt = car.power_kw.value / ((car.mass_kg.value + n.towing_kg) / 1000)
        need = float(th.get("towing", 45))
        out += [Num("power per tonne with the trailer", round(kwt), "kW/t"),
                Num("enough for towing from", need, "kW/t", "ASSUMPTION")]  # fmt: skip
        ok = ok and kwt >= need
    return CheckResult("USAGE_POWER", "FITS" if ok else "DOES_NOT_FIT",
                       "Enough power for your use." if ok else "Little power for your use: " + ", ".join(
                           f"{x.label} {x.value:g} {x.unit}" for x in out[::2]), out)  # fmt: skip


REAL_RANGE_FACTOR = 1.2  # WLTP → real-world (spec 006 research R6; assumption)


def _range(n: Needs, car: CarFacts, rules: Mapping[str, Any]) -> CheckResult | None:
    """A BEV's range against the daily distance. A plug-in or hybrid continues on fuel: no range limit."""
    if not n.daily_km or (car.powertrain is not None and car.powertrain.upper() != "BEV"):
        return None
    if car.consumption is not None and car.battery_kwh is not None:
        rng, how = car.battery_kwh.value / car.consumption.value * 100, "battery ÷ consumption"
    elif car.range_wltp is not None:
        rng, how = car.range_wltp.value / REAL_RANGE_FACTOR, f"WLTP range ÷ {REAL_RANGE_FACTOR:g}"
    elif car.battery_kwh is None:
        return None
    else:
        return CheckResult("USAGE_RANGE", "UNKNOWN", "Consumption is not known.", missing=["consumption"])
    margin = float((rules.get("usage") or {}).get("bev_range_margin", 1.6))
    need = n.daily_km * margin
    fits = rng >= need
    return CheckResult("USAGE_RANGE", "FITS" if fits else "DOES_NOT_FIT",
                       f"Range about {rng:.0f} km; {n.daily_km} km a day needs about {need:.0f} km with a margin.",
                       [Num("estimated range", round(rng), "km", "ASSUMPTION", (), (how,)),
                        Num("needed with a margin", round(need), "km", "ASSUMPTION")])  # fmt: skip


def evaluate(n: Needs, cars: Sequence[CarFacts], rules: Mapping[str, Any], year: int) -> list[CarFeasibility]:
    out = []
    for car in cars:
        checks = [r for r in (_budget(n, car, rules, year), _running(n, car), _space(n, car, rules),
                              _power(n, car, rules), _range(n, car, rules)) if r is not None]  # fmt: skip
        out.append(CarFeasibility(car.key, car.label, checks))
    return out


def fingerprint(n: Needs, results: Sequence[CarFeasibility]) -> str | None:
    """Identity of the constraints and the problems found; None when everything fits."""
    problems = [(r.car_key, c.check, c.verdict) for r in results for c in r.problems]
    if not problems:
        return None
    payload = json.dumps({"needs": asdict(n), "problems": problems}, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:32]
