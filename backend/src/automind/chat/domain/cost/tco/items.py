"""Each item of the ownership cost on its own: maintenance (sourced or default), energy, tyres, road tax, big tickets
due, depreciation (new and used), repair reserve by age band."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from automind.chat.domain.cost import energy as en
from automind.chat.domain.cost.tco.model import CLASSES, Basis, BigTicket, Kind, TcoCar, TcoItem, TcoRates


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


def maintenance_item(car: TcoCar, r: TcoRates, km: int, years: int) -> TcoItem:
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
    return en.fuel_consumption(energy_car(car), r.real_world_factor)


def energy_car(car: TcoCar) -> en.EnergyCar:
    return en.EnergyCar(
        powertrain=(car.powertrain or "ICE").upper(), fuel=car.fuel, consumption=car.consumption,
        consumption_real=car.consumption_real, consumption_nedc=car.consumption_nedc,
        consumption_ev=car.consumption_ev, consumption_ev_real=car.consumption_ev_real,
        ev_real_meter=car.ev_real_meter, consumption_cs=car.consumption_cs, battery_kwh=car.battery_kwh,
        consumption_weighted=car.consumption_weighted,
        range_wltp=car.range_wltp, range_real=car.range_real, stated=car.stated,
        consumption_ev_cltc=car.consumption_ev_cltc, range_cltc=car.range_cltc, cltc_pair=car.cltc_pair,
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
    return en.estimate(energy_car(car), energy_rates(r), use)


def energy_item(car: TcoCar, r: TcoRates, km: int, years: int) -> TcoItem:
    e = energy_estimate(car, r, km)
    item = _item("ENERGY", e.label, e.annual_eur, "ASSUMPTION", e.inputs, years)
    return replace(item, parts=list(e.parts), missing=list(e.missing), estimate=e)


def tyres_item(car: TcoCar, r: TcoRates, km: int, years: int) -> TcoItem:
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


def road_tax_item(car: TcoCar, r: TcoRates, years: int) -> TcoItem:
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


def big_tickets_item(car: TcoCar, r: TcoRates, km: int, years: int) -> list[TcoItem]:
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


def depreciation_item(car: TcoCar, years: int) -> TcoItem:
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


def reserve_item(car: TcoCar, r: TcoRates, years: int) -> TcoItem:
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
