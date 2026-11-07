"""What the criteria scores and the insights read of a car: its `CarFacts` and its insight values (a used car's
price is its used price, never the new one)."""

from __future__ import annotations

from automind.chat.application.services.report.contracts import Curves, LoadedCar
from automind.chat.application.services.report.facts.car import num, short_name, txt
from automind.chat.application.services.report.facts.quality import (
    engineering_completeness,
    reliability_summary,
    review_summary,
)
from automind.chat.application.services.report.facts.retention import retention_points
from automind.chat.domain.assessment import dragrace
from automind.chat.domain.assessment import metrics as scoring
from automind.chat.domain.verdict import insights as ins

INSIGHT_ATTRS = ("boot_volume", "consumption", "measured_0_100", "max_power", "max_torque", "curb_mass",
                 "official_price_es", "ground_clearance", "rear_legroom", "euro_ncap_stars", "top_speed")  # fmt: skip


def car_facts(
    car: LoadedCar,
    sim: dragrace.CarResult | None = None,
    *,
    condition: str = "NEW",
    age_years: int | None = None,
    annual_cost_eur: float | None = None,
    year: int | None = None,
    energy_eur_per_100km: float | None = None,
    mileage_km: int | None = None,
    used_price_eur: float | None = None,
    period_cost_eur: float | None = None,
    period_years: int | None = None,
) -> scoring.CarFacts:
    v = car["variant"]
    return scoring.CarFacts(
        car_id=v.id,
        label=v.label,
        powertrain=v.powertrain,
        power_kw=num(car, "max_power"),
        torque_nm=num(car, "max_torque"),
        mass_kg=num(car, "curb_mass"),
        displacement_cc=num(car, "displacement"),
        drivetrain=txt(car, "drivetrain"),
        top_speed_kmh=num(car, "top_speed"),
        consumption=num(car, "consumption"),
        boot_l=num(car, "boot_volume"),
        seats=num(car, "seats"),
        price_eur=num(car, "official_price_es"),
        service_interval_km=num(car, "service_interval_km"),
        service_interval_months=num(car, "service_interval_months"),
        sim_0_100=sim.t_0_100 if sim else None,
        sim_400m=sim.t_400m if sim else None,
        rear_legroom_mm=num(car, "rear_legroom"),
        ground_clearance_mm=num(car, "ground_clearance"),
        low_range=txt(car, "low_range"),
        euro_ncap=num(car, "euro_ncap_stars"),
        euro_ncap_year=num(car, "euro_ncap_year"),
        vehicle_class=v.vehicle_class,
        brand_positioning=v.brand_positioning,
        condition=condition,
        age_years=age_years,
        mileage_km=mileage_km,
        used_price_eur=used_price_eur if condition == "USED" else None,
        annual_cost_eur=annual_cost_eur,
        period_cost_eur=period_cost_eur,
        period_years=period_years if period_cost_eur is not None else None,
        energy_eur_per_100km=energy_eur_per_100km,
        reliability=reliability_summary(car),
        reviews=review_summary(car),
        engineering_completeness=engineering_completeness(car),
        new_generation_since=scoring.new_generation_since(getattr(v, "generation_years_from", None), year),
    )


def insight_values(
    car: LoadedCar,
    *,
    annual_cost: float | None,
    reliability_score: float | None,
    energy_eur_per_unit: float | None,
    accel_0_100: float | None = None,
    retention_curve: Curves | None = None,
    used: bool = False,
    used_price_eur: float | None = None,
    period_total: float | None = None,
    cost_curve: tuple[float, ...] = (),
) -> ins.CarValues:
    """A used car's price is what it costs used (spec 008 FR-023): its sourced used price, else no price at all —
    the new price never stands for a used car in the verdict or the text."""

    v = car["variant"]
    values: dict[str, float] = {}
    conf: dict[str, str] = {}
    srcs: dict[str, list[str]] = {}
    for k in INSIGHT_ATTRS:
        sv = car["values"].get(k)
        if sv is not None and sv.available and sv.value_num is not None:
            values[k], conf[k], srcs[k] = float(sv.value_num), str(sv.confidence or "MEDIUM"), list(sv.claim_ids or [])
    if used:
        values.pop("official_price_es", None)
        srcs.pop("official_price_es", None)
        if used_price_eur is not None:
            values["official_price_es"], conf["official_price_es"] = float(used_price_eur), "MEDIUM"
    claimed = car["values"].get("claimed_0_100")
    if claimed is not None and claimed.available and claimed.value_num is not None:
        values["accel_0_100"], conf["accel_0_100"] = float(claimed.value_num), str(claimed.confidence or "MEDIUM")
    elif accel_0_100 is not None:
        values["accel_0_100"], conf["accel_0_100"] = accel_0_100, "LOW"  # simulated
    # running costs per year (secondary) and the total over the user's period with the value lost (what ownership
    # cost compares, chat 5821ac77)
    costs = {k: x for k, x in (("tco_per_year", annual_cost), ("tco_period", period_total)) if x is not None}
    values |= costs
    conf |= dict.fromkeys(costs, "MEDIUM")
    if reliability_score is not None:
        values["reliability_score"], conf["reliability_score"] = reliability_score, "MEDIUM"
    five = next((p for p in retention_points(car, retention_curve or {}) if p["years"] == 5), None)
    if five is not None and five["share"]:
        values["value_retention_5y"] = round(five["share"] * 100, 1)
        conf["value_retention_5y"] = "MEDIUM" if five["basis"] == "SOURCED" else "LOW"
    return ins.CarValues(v.id, short_name(v), values, conf, srcs, energy_eur_per_unit, tuple(cost_curve))
