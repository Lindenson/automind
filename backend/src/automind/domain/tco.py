"""Ownership cost (TCO) engine (FR-033..FR-035; research R9). Pure and deterministic.

Items: MAINTENANCE, ENERGY, TYRES, ROAD_TAX and, for used cars, BIG_TICKET (documented age/mileage
items due within the horizon) and BASE_RESERVE (age band × class table). DEPRECIATION (spec 007 FR-016) is the
value lost over the user's ownership period: it is part of the period total, not of the yearly running cost
(the running cost is what the monthly limit and the ownership-cost score compare).

Horizon: `years` (the user's ownership period) or `rates.horizon_years`. Every item is labelled
SOURCED or ASSUMPTION and lists its inputs (constitution XI). Items without data are "not included",
never guessed.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Literal

from automind.domain import energy as en

RULES_VERSION = "tco-1.2"  # 1.2: energy model per powertrain (spec 006)
Basis = Literal["SOURCED", "ASSUMPTION"]
Kind = Literal["MAINTENANCE", "ENERGY", "TYRES", "ROAD_TAX", "BIG_TICKET", "BASE_RESERVE", "DEPRECIATION"]
CLASSES = ("small", "compact", "mid_large", "premium_suv_4x4")


@dataclass(frozen=True)
class TcoRates:
    fuel_eur_per_l: float
    diesel_eur_per_l: float
    electricity_eur_per_kwh: float
    labour_eur_per_h: float
    annual_km: int
    horizon_years: int
    tyre_life_km: Mapping[str, float]
    tyre_set_eur: Mapping[str, float]
    service_hours: Mapping[str, float]
    service_parts_eur: Mapping[str, float]
    default_interval_km: Mapping[str, float]
    big_ticket_default_eur: float
    road_tax_eur_per_cvf: float | None
    base_reserve: Mapping[str, list[float]]  # class -> per age band [0-4, 5-9, 10-14, 15+]
    max_maintenance_eur: Mapping[str, float] = field(default_factory=dict)  # sanity cap per class and year
    real_world_factor: Mapping[str, float] = field(default_factory=dict)  # official cycle → real use, per powertrain
    energy: en.EnergyConfig = field(default_factory=en.EnergyConfig)  # config/energy.yaml (spec 006)

    @classmethod
    def from_config(cls, d: Mapping[str, Any], overrides: Mapping[str, float | None] | None = None) -> TcoRates:
        o = {k: v for k, v in (overrides or {}).items() if v is not None}
        table = d["base_reserve_eur_per_year"]
        energy = en.EnergyConfig.from_config(
            d.get("energy"),
            home_override=o.get("home_electricity_eur_per_kwh", o.get("electricity_eur_per_kwh")),
            ac_override=o.get("public_ac_eur_per_kwh"),
            dc_override=o.get("public_dc_eur_per_kwh"),
            night=bool(o.get("night_tariff")),
            today=d.get("today"),
        )
        petrol = energy.petrol.value if energy.petrol else d["fuel_eur_per_l"]
        diesel = energy.diesel.value if energy.diesel else d["diesel_eur_per_l"]
        return cls(
            fuel_eur_per_l=float(o.get("fuel_eur_per_l", petrol)),
            diesel_eur_per_l=float(o.get("diesel_eur_per_l", diesel)),
            electricity_eur_per_kwh=float(o.get("electricity_eur_per_kwh", d["electricity_eur_per_kwh"])),
            labour_eur_per_h=float(o.get("labour_eur_per_h", d["labour_eur_per_h"])),
            annual_km=int(d["annual_km"]),
            horizon_years=int(d["horizon_years"]),
            tyre_life_km=dict(d["tyre_life_km"]),
            tyre_set_eur=dict(d["tyre_set_eur"]),
            service_hours=dict(d["service_hours"]),
            service_parts_eur=dict(d["service_parts_eur"]),
            default_interval_km=dict(d["default_interval_km"]),
            big_ticket_default_eur=float(d["big_ticket_default_eur"]),
            road_tax_eur_per_cvf=d.get("road_tax_eur_per_cvf"),
            base_reserve={k: [float(x) for x in v] for k, v in table.items() if k in CLASSES},
            max_maintenance_eur={k: float(v) for k, v in (d.get("max_maintenance_eur_per_year") or {}).items()},
            real_world_factor={k: float(v) for k, v in (d.get("real_world_factor") or {}).items()},
            energy=energy,
        )


@dataclass(frozen=True)
class MaintenanceSched:
    item: str
    interval_km: float | None = None
    interval_months: float | None = None
    cost_eur: float | None = None  # sourced price of this service, if published
    evidence_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class BigTicket:
    component: str
    age_from: int | None = None
    age_to: int | None = None
    mileage_from: int | None = None
    mileage_to: int | None = None
    cost_eur: float | None = None
    evidence_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TcoCar:
    car_id: str
    label: str
    powertrain: str
    fuel: str | None = None  # petrol | diesel (ICE/hybrids)
    consumption: float | None = None  # official WLTP, l/100 km or kWh/100 km (BEV)
    consumption_real: float | None = None  # real-world (tests), preferred for the fuel bill
    consumption_nedc: float | None = None  # old cycle, used only without WLTP and real-world figures
    vehicle_class: str | None = None
    condition: str = "NEW"
    age_years: int | None = None
    mileage_km: int | None = None
    fiscal_hp: float | None = None
    road_tax_eur: float | None = None  # sourced annual road tax
    maintenance: list[MaintenanceSched] = field(default_factory=list)
    big_tickets: list[BigTicket] = field(default_factory=list)
    price_eur: float | None = None  # official new price (ES)
    used_price_eur: float | None = None  # spec 008: sourced used price for its year (a used car's value now)
    retention: Mapping[int, float] = field(default_factory=dict)  # sourced value share after N years (3, 5)
    retention_curve: Mapping[float, float] = field(default_factory=dict)  # class curve (assumption), age -> share
    # spec 006: electric facts and the user's use (daily km, climate, home charging) for the energy model
    consumption_ev: float | None = None
    consumption_ev_real: float | None = None
    ev_real_meter: str | None = None
    consumption_cs: float | None = None
    consumption_weighted: float | None = None  # PHEV official WLTP weighted l/100 km (spec 009 FR-014 estimate)
    battery_kwh: float | None = None
    range_wltp: float | None = None
    range_real: float | None = None
    use: en.UsageContext | None = None
    new_in_market: bool = False  # a make recently arrived in Spain: no class depreciation curve (spec 006 FR-018)
    stated: Mapping[str, tuple[float, str]] = field(default_factory=dict)  # the user's own consumption figures


@dataclass(frozen=True)
class TcoItem:
    kind: Kind
    label: str
    annual_eur: float | None
    five_year_eur: float | None
    basis: Basis
    inputs: list[str]
    evidence_ids: list[str] = field(default_factory=list)
    parts: list[en.EnergyPart] = field(default_factory=list)  # ENERGY only: electricity / fuel split (spec 006)
    missing: list[str] = field(default_factory=list)  # ENERGY only: inputs that stop the computation
    estimate: en.EnergyEstimate | None = None  # ENERGY only


@dataclass(frozen=True)
class TcoEstimate:
    car_id: str
    label: str
    condition: str
    age_years: int | None
    annual_km: int
    items: list[TcoItem]
    annual_total: float  # running cost per year (without depreciation)
    five_year_total: float  # total over `years` (running + depreciation); the name is kept for stored rows
    rules_version: str = RULES_VERSION
    years: int = 5  # the period the totals cover
    depreciation_left_out: bool = False  # another compared car has no value data: totals are running cost only

    @property
    def period_total(self) -> float:
        return self.five_year_total


def _item(
    kind: Kind,
    label: str,
    annual: float | None,
    basis: Basis,
    inputs: list[str],
    years: int,
    evidence: list[str] | None = None,
) -> TcoItem:
    a = round(annual, 2) if annual is not None else None
    return TcoItem(kind, label, a, round(a * years, 2) if a is not None else None, basis, inputs, evidence or [])


def _cls(car: TcoCar) -> tuple[str, list[str]]:
    if car.vehicle_class in CLASSES:
        return car.vehicle_class, [f"class {car.vehicle_class}"]
    return "compact", ["class unknown → compact (assumption)"]


MIN_INTERVAL_KM = 1000  # shorter "intervals" are extraction errors (e.g. 16 for 16,000 km), never a schedule


def _services_per_year(interval_km: float | None, interval_months: float | None, km: int) -> float:
    by_km = km / interval_km if interval_km and interval_km >= MIN_INTERVAL_KM else 0.0
    by_time = 12 / interval_months if interval_months else 0.0
    return max(by_km, by_time)


def _maintenance(car: TcoCar, r: TcoRates, km: int, years: int) -> TcoItem:
    pt = car.powertrain if car.powertrain in r.service_hours else "ICE"
    assumed = r.service_hours[pt] * r.labour_eur_per_h + r.service_parts_eur[pt]
    sourced = _sourced_maintenance(car, r, km, years, assumed, pt) if car.maintenance else None
    cap = r.max_maintenance_eur.get(car.vehicle_class or "compact")
    if sourced is not None and cap and (sourced.annual_eur or 0) > cap:
        default = _default_maintenance(r, km, years, assumed, pt)
        return replace(default, inputs=[
            f"published schedule gave €{sourced.annual_eur:,.0f}/year — implausible for this class "
            f"(cap €{cap:,.0f}); estimate used instead: 1 service / {r.default_interval_km.get(pt, 15000):.0f} km",
            *default.inputs[1:]])  # fmt: skip
    return sourced if sourced is not None else _default_maintenance(r, km, years, assumed, pt)


def _default_maintenance(r: TcoRates, km: int, years: int, assumed: float, pt: str) -> TcoItem:
    per_year = km / r.default_interval_km.get(pt, 15000)
    return _item(
        "MAINTENANCE",
        "Scheduled maintenance",
        per_year * assumed,
        "ASSUMPTION",
        [
            f"no published schedule: 1 service / {r.default_interval_km.get(pt, 15000):.0f} km",
            f"labour {r.service_hours[pt]} h × €{r.labour_eur_per_h:.0f}/h + parts €{r.service_parts_eur[pt]:.0f}",
            f"{km:,} km/year",
        ],
        years,
    )


def _sourced_maintenance(car: TcoCar, r: TcoRates, km: int, years: int, assumed: float, pt: str) -> TcoItem:
    """Jobs with a sourced cost add that cost. Jobs with only a sourced interval are done at the scheduled
    visits, so they cost visits, not one full service each: the most frequent of them sets how many visits a
    year are paid (one assumed service each). The same job listed twice (e.g. in two languages) counts once."""
    priced, basis, inputs, ev = 0.0, "SOURCED", [], []
    visits, unpriced = 0.0, []
    seen: set[tuple[int, int]] = set()
    for m in car.maintenance:
        sig = (round((m.interval_km or 0) / 1000), int(m.interval_months or 0))
        n = _services_per_year(m.interval_km, m.interval_months, km)
        if n == 0:
            continue
        ev += m.evidence_ids
        if m.cost_eur is not None:
            if sig != (0, 0) and sig in seen:
                continue
            seen.add(sig)
            priced += n * m.cost_eur
            inputs.append(f"{m.item}: €{m.cost_eur:.0f} sourced")
        else:
            visits = max(visits, n)
            unpriced.append(m.item)
    if unpriced:
        basis = "ASSUMPTION"
        inputs.append(
            f"{', '.join(unpriced)}: intervals sourced, done at {visits:.2g} service visit(s)/year; "
            f"visit = labour {r.service_hours[pt]} h × €{r.labour_eur_per_h:.0f}/h"
            f" + parts €{r.service_parts_eur[pt]:.0f}"
        )
    inputs.append(f"{km:,} km/year")
    total = priced + visits * assumed
    return _item("MAINTENANCE", "Scheduled maintenance", total, basis, inputs, years, ev)  # type: ignore[arg-type]


def energy_consumption(car: TcoCar, r: TcoRates) -> tuple[float | None, str]:
    """Fuel consumption for a combustion car or hybrid (kept for callers; the model is in domain/energy.py)."""
    return en.fuel_consumption(_energy_car(car), r.real_world_factor)


def _energy_car(car: TcoCar) -> en.EnergyCar:
    return en.EnergyCar(
        powertrain=(car.powertrain or "ICE").upper(), fuel=car.fuel, consumption=car.consumption,
        consumption_real=car.consumption_real, consumption_nedc=car.consumption_nedc,
        consumption_ev=car.consumption_ev, consumption_ev_real=car.consumption_ev_real,
        ev_real_meter=car.ev_real_meter, consumption_cs=car.consumption_cs, battery_kwh=car.battery_kwh,
        consumption_weighted=car.consumption_weighted,
        range_wltp=car.range_wltp, range_real=car.range_real, stated=car.stated,
    )  # fmt: skip


def _fuel(r: TcoRates, sourced: en.Price | None, value: float, label: str) -> en.Price:
    if sourced is not None and sourced.value == value:
        return en.Price(value, "l", label, sourced.basis, sourced.as_of, sourced.stale)
    basis = "USER" if sourced is not None else "ASSUMPTION"  # a value other than the configured one is the user's
    return en.Price(value, "l", label, basis)


def energy_rates(r: TcoRates) -> en.Rates:
    return en.Rates(
        petrol=_fuel(r, r.energy.petrol, r.fuel_eur_per_l, "petrol"),
        diesel=_fuel(r, r.energy.diesel, r.diesel_eur_per_l, "diesel"),
        real_world_factor=r.real_world_factor,
        cfg=r.energy,
    )


def energy_estimate(car: TcoCar, r: TcoRates, km: int) -> en.EnergyEstimate:
    use = car.use or en.UsageContext(annual_km=km)
    if use.annual_km != km:
        use = replace(use, annual_km=km)
    return en.estimate(_energy_car(car), energy_rates(r), use)


def _energy(car: TcoCar, r: TcoRates, km: int, years: int) -> TcoItem:
    e = energy_estimate(car, r, km)
    item = _item("ENERGY", e.label, e.annual_eur, "ASSUMPTION", e.inputs, years)
    return replace(item, parts=list(e.parts), missing=list(e.missing), estimate=e)


def _tyres(car: TcoCar, r: TcoRates, km: int, years: int) -> TcoItem:
    cls, notes = _cls(car)
    annual = r.tyre_set_eur[cls] * km / r.tyre_life_km[cls]
    return _item(
        "TYRES",
        "Tyres",
        annual,
        "ASSUMPTION",
        [f"set €{r.tyre_set_eur[cls]:.0f}, life {r.tyre_life_km[cls]:,.0f} km", *notes, f"{km:,} km/year"],
        years,
    )


def _road_tax(car: TcoCar, r: TcoRates, years: int) -> TcoItem:
    if car.road_tax_eur is not None:
        return _item("ROAD_TAX", "Road tax (IVTM)", car.road_tax_eur, "SOURCED", ["sourced annual rate"], years)
    if r.road_tax_eur_per_cvf is not None and car.fiscal_hp:
        return _item(
            "ROAD_TAX",
            "Road tax (IVTM)",
            r.road_tax_eur_per_cvf * car.fiscal_hp,
            "ASSUMPTION",
            [f"{car.fiscal_hp} CVF × €{r.road_tax_eur_per_cvf}/CVF (configured)"],
            years,
        )
    return _item(
        "ROAD_TAX",
        "Road tax (IVTM): not included — no rate found",
        None,
        "ASSUMPTION",
        ["municipal rate not found"],
        years,
    )


def _due(b: BigTicket, age: int | None, mileage: int | None, km: int, years: int) -> bool:
    if age is not None and b.age_from is not None:
        hi = b.age_to if b.age_to is not None else b.age_from
        if hi >= age and b.age_from <= age + years:
            return True
    if mileage is not None and b.mileage_from is not None:
        hi_km = b.mileage_to if b.mileage_to is not None else b.mileage_from
        if hi_km >= mileage and b.mileage_from <= mileage + km * years:
            return True
    return False


def _big_tickets(car: TcoCar, r: TcoRates, km: int, years: int) -> list[TcoItem]:
    out = []
    for b in car.big_tickets:
        if not _due(b, car.age_years, car.mileage_km, km, years):
            continue
        sourced = b.cost_eur is not None
        cost = b.cost_eur if sourced else r.big_ticket_default_eur
        assert cost is not None
        window = (
            f"age {b.age_from}–{b.age_to}"
            if b.age_from is not None
            else f"{b.mileage_from:,}–{b.mileage_to or b.mileage_from:,} km"
        )
        inputs = [
            f"documented for {window} ({len(b.evidence_ids)} source(s))",
            "cost sourced" if sourced else f"cost €{cost:.0f} (assumption)",
        ]
        out.append(
            TcoItem(
                "BIG_TICKET",
                f"Due within {years} years: {b.component}",
                round(cost / years, 2),
                round(cost, 2),
                "SOURCED" if sourced else "ASSUMPTION",
                inputs,
                list(b.evidence_ids),
            )
        )
    return out


def _curve(curve: Mapping[float, float], t: float) -> float | None:
    pts = sorted((float(k), float(v)) for k, v in curve.items())
    if not pts:
        return None
    if t <= pts[0][0]:
        return pts[0][1]
    for (a, va), (b, vb) in zip(pts, pts[1:], strict=False):
        if a <= t <= b:
            return va + (vb - va) * (t - a) / (b - a)
    return pts[-1][1]


def value_share(
    t: float, sourced: Mapping[int, float], curve: Mapping[float, float]
) -> tuple[float | None, Basis, str]:
    """Share of the new price left at age `t`. Sourced 3- and 5-year points are interpolated (from 1.0 at 0);
    beyond the last sourced point the class curve carries it on from there (assumption rate). Without sourced
    points: the class curve (assumption)."""
    pts = sorted((float(k), float(v)) for k, v in sourced.items() if v)
    if pts:
        last_t, last_v = pts[-1]
        if t <= last_t:
            return (
                _curve({0.0: 1.0, **dict(pts)}, t),
                "SOURCED",
                f"sourced value after {', '.join(f'{k:g}' for k, _ in pts)} years",
            )
        base, there = _curve(curve, last_t), _curve(curve, t)
        if base and there is not None:
            return (
                last_v * there / base,
                "ASSUMPTION",
                (f"sourced value after {last_t:g} years, then the class depreciation rate (assumption)"),
            )
    share = _curve(curve, t)
    return share, "ASSUMPTION", "class depreciation curve (assumption)"


def _used_depreciation(car: TcoCar, years: int) -> TcoItem | None:
    """A used car loses value from what it is worth now (spec 008 FR-024): the sourced used price, carried forward
    by the share it keeps between its age now and its age at the end."""
    age = max(1, car.age_years or 0)
    if car.condition != "USED" or not car.used_price_eur:
        return None
    start, b0, _ = value_share(age, car.retention, car.retention_curve)
    end, b1, how = value_share(age + years, car.retention, car.retention_curve)
    if not start or end is None:
        return None
    value_now = car.used_price_eur
    value_then = value_now * end / start
    loss = max(0.0, value_now - value_then)
    inputs = [f"value now €{value_now:,.0f} (sourced used price, {age} years)",
              f"value after {years} more years ≈ €{value_then:,.0f}: {how}"]  # fmt: skip
    return TcoItem("DEPRECIATION", f"Depreciation over {years} years", round(loss / years, 2), round(loss, 2),
                   "SOURCED" if b0 == b1 == "SOURCED" else "ASSUMPTION", inputs)  # fmt: skip


def _depreciation(car: TcoCar, years: int) -> TcoItem:
    if (used := _used_depreciation(car, years)) is not None:
        return used
    if not car.price_eur:
        return _item("DEPRECIATION", "Depreciation: not included (price not found)", None, "ASSUMPTION",
                     ["official price not found"], years)  # fmt: skip
    if car.new_in_market and not car.retention:
        return _item("DEPRECIATION", "Depreciation: insufficient data for this brand", None, "ASSUMPTION",
                     ["recent make in Spain: no sourced resale values, no class curve used"], years)  # fmt: skip
    age = max(1, car.age_years or 0) if car.condition == "USED" else 0  # a used car is never valued as new (FR-022)
    start, b0, _ = value_share(age, car.retention, car.retention_curve) if age else (1.0, "SOURCED", "")
    end, b1, how = value_share(age + years, car.retention, car.retention_curve)
    if start is None or end is None:
        return _item("DEPRECIATION", "Depreciation: not included (no value data)", None, "ASSUMPTION",
                     ["no value data for this class"], years)  # fmt: skip
    value_now, value_then = car.price_eur * start, car.price_eur * end
    loss = max(0.0, value_now - value_then)
    basis: Basis = "SOURCED" if b0 == b1 == "SOURCED" else "ASSUMPTION"
    inputs = [f"new price €{car.price_eur:,.0f}"]
    if age:
        inputs.append(f"value now ≈ €{value_now:,.0f} at {age} years (estimate from the new price: no sourced "
                      "used price)")  # fmt: skip
    inputs += [f"value after {years} years ≈ €{value_then:,.0f} ({end * 100:.0f}% of new): {how}"]
    return TcoItem("DEPRECIATION", f"Depreciation over {years} years", round(loss / years, 2), round(loss, 2),
                   basis, inputs)  # fmt: skip


def _band(age: int) -> int:
    return 0 if age <= 4 else 1 if age <= 9 else 2 if age <= 14 else 3


def _reserve(car: TcoCar, r: TcoRates, years: int) -> TcoItem:
    cls, notes = _cls(car)
    age = max(1, car.age_years or 0)
    annual = r.base_reserve[cls][_band(age)]
    bands = ("0–4", "5–9", "10–14", "15+")
    return _item(
        "BASE_RESERVE",
        "Base repair reserve",
        annual,
        "ASSUMPTION",
        [f"age band {bands[_band(age)]} years", *notes, "table in config/rates.yaml"],
        years,
    )


def compute(car: TcoCar, rates: TcoRates, annual_km: int | None = None, years: int | None = None) -> TcoEstimate:
    km = annual_km or rates.annual_km
    years = years or rates.horizon_years
    items = [
        _maintenance(car, rates, km, years),
        _energy(car, rates, km, years),
        _tyres(car, rates, km, years),
        _road_tax(car, rates, years),
    ]
    if car.condition == "USED":
        items += _big_tickets(car, rates, km, years)
        items.append(_reserve(car, rates, years))
    items.append(_depreciation(car, years))
    running = [i for i in items if i.kind != "DEPRECIATION"]
    annual = round(sum(i.annual_eur for i in running if i.annual_eur is not None), 2)
    period = round(sum(i.five_year_eur for i in items if i.five_year_eur is not None), 2)
    return TcoEstimate(car.car_id, car.label, car.condition, car.age_years, km, items, annual, period, years=years)


MAX_PAYBACK_YEARS = 15  # beyond this a payback is no payback (incident 2026-11-03: "after 77 years")


def depreciation_known(e: TcoEstimate) -> bool:
    """The period total of `e` includes the value the car loses (chat 5821ac77: a verdict on running costs alone
    called the dearer car the saving)."""
    return not e.depreciation_left_out and any(i.kind == "DEPRECIATION" and i.five_year_eur is not None
                                               for i in e.items)  # fmt: skip


def cost_curve(car: TcoCar, rates: TcoRates, annual_km: int | None = None,
               max_years: int = MAX_PAYBACK_YEARS) -> tuple[float, ...]:  # fmt: skip
    """Total cost of owning `car` (running costs + value lost) after 1..max_years years, from the same model as the
    period total. Empty when the value loss is not known: a payback is never computed from running costs alone."""
    out = []
    for t in range(1, max_years + 1):
        e = compute(car, rates, annual_km, t)
        if not depreciation_known(e):
            return ()
        out.append(e.period_total)
    return tuple(out)


def payback_years(dear: Sequence[float], cheap: Sequence[float]) -> float | None:
    """When the total cost of `dear` (the car that costs more at first) drops to the total of `cheap`: years,
    interpolated between whole years, rounded up to 0.5. None when it never does within the curves."""
    n = min(len(dear), len(cheap))
    prev = 0.0
    for t in range(n):
        d = dear[t] - cheap[t]
        if d <= 0:
            if t == 0:
                return 1.0
            frac = prev / (prev - d) if prev != d else 1.0
            return max(1.0, math.ceil(round((t + frac) * 2, 6)) / 2)
        prev = d
    return None


def like_for_like(estimates: list[TcoEstimate]) -> list[TcoEstimate]:
    """When depreciation is known for some cars and not for others, the period totals leave it out for all, so
    one car is never cheaper only because its value loss is unknown (spec 006 FR-014)."""

    def known(e: TcoEstimate) -> bool:
        return any(i.kind == "DEPRECIATION" and i.annual_eur is not None for i in e.items)

    if len({known(e) for e in estimates}) < 2:
        return estimates
    out = []
    for e in estimates:
        running = round(sum(i.five_year_eur for i in e.items if i.kind != "DEPRECIATION"
                            and i.five_year_eur is not None), 2)  # fmt: skip
        out.append(replace(e, five_year_total=running, depreciation_left_out=True))
    return out
