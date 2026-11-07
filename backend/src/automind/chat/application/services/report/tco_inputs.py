"""The ownership-cost inputs of one car (`tco.TcoCar`) from its validated data: specs, sourced maintenance items,
used-car issues with an age or mileage, value retention, the energy the person stated."""

from __future__ import annotations

from automind.chat.application.services.report.contracts import Curves, LoadedCar
from automind.chat.application.services.report.facts.car import num, txt
from automind.chat.application.services.report.facts.retention import class_curve, sourced_retention
from automind.chat.domain.cost import energy, tco
from automind.shared.vehicle import identity


async def tco_car(
    car: LoadedCar, condition: str, age_years: int | None, mileage_km: int | None,
    retention_curve: Curves | None = None, use: energy.UsageContext | None = None, new_in_market: bool = False,
    stated: dict[str, tuple[float, str]] | None = None, used_price_eur: float | None = None,
) -> tco.TcoCar:  # fmt: skip
    """Assemble TCO inputs from validated data: specs, sourced maintenance items, used-car issues."""
    v = car["variant"]
    fuel = v.fuel
    if fuel not in ("petrol", "diesel"):  # a hybrid kind or unknown: the liquid fuel from the engine and the name
        fuel = identity.liquid_fuel(f"{txt(car, 'engine') or ''} {v.model} {v.variant_name}") or "petrol"
    return tco.TcoCar(
        car_id=v.id, label=v.label, powertrain=v.powertrain, vehicle_class=v.vehicle_class,
        fuel=None if v.powertrain == "BEV" else fuel,
        # energy: the test cycles, the real-world figures and the electric range
        consumption=num(car, "consumption"), consumption_real=num(car, "consumption_real"),
        consumption_nedc=num(car, "consumption_nedc"), consumption_ev=num(car, "consumption_ev"),
        consumption_ev_real=num(car, "consumption_ev_plug") or num(car, "consumption_ev_real")
        or (num(car, "consumption_real") if v.powertrain == "BEV" else None),
        ev_real_meter="plug" if num(car, "consumption_ev_plug") else None,
        consumption_cs=num(car, "consumption_cs"), consumption_weighted=num(car, "consumption_weighted"),
        battery_kwh=num(car, "battery_kwh"), range_wltp=num(car, "range_wltp"), range_real=num(car, "range_real"),
        consumption_ev_cltc=num(car, "consumption_ev_cltc"), range_cltc=num(car, "range_cltc"),
        cltc_pair=car.get("cltc_pair"), use=use,
        # the car as owned: condition, taxes, maintenance, prices and value kept
        condition=condition, age_years=age_years, mileage_km=mileage_km, fiscal_hp=num(car, "fiscal_hp"),
        maintenance=_schedule(car), big_tickets=_tickets(car), price_eur=num(car, "official_price_es"),
        used_price_eur=used_price_eur if condition == "USED" else None, retention=sourced_retention(car),
        retention_curve=class_curve(v.vehicle_class, retention_curve or {}), new_in_market=new_in_market,
        stated=stated or {},
    )  # fmt: skip


def _schedule(car: LoadedCar) -> list[tco.MaintenanceSched]:
    """The sourced maintenance items with an interval, else the service interval from the specs."""
    sched = [tco.MaintenanceSched(m.item, m.interval_km, m.interval_months, m.cost_eur, list(m.evidence_ids or []))
             for m in car.get("maintenance", []) if m.interval_km or m.interval_months]  # fmt: skip
    if not sched and (num(car, "service_interval_km") or num(car, "service_interval_months")):
        sched = [tco.MaintenanceSched("service", num(car, "service_interval_km"), num(car, "service_interval_months"))]
    return sched


def _tickets(car: LoadedCar) -> list[tco.BigTicket]:
    """The used-car issues that come with an age or a mileage (a big repair to expect)."""
    return [tco.BigTicket(i.component, i.age_from, i.age_to, i.mileage_from, i.mileage_to, None, [i.evidence_id])
            for i in car.get("used_issues", []) if i.age_from is not None or i.mileage_from is not None]  # fmt: skip
