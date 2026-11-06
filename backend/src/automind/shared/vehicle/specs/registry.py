"""The specification attribute registry: every attribute a car can have, its canonical unit, tier and converter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal

from automind.shared.vehicle import units
from automind.shared.vehicle.specs import converters

Kind = Literal["number", "text"]


Category = Literal["specs", "engineering", "measured", "price", "maintenance"]


@dataclass(frozen=True)
class Attr:
    key: str
    label: str
    unit: str | None  # canonical unit
    kind: Kind
    category: Category
    tolerance: float  # relative for numbers (0.02 = 2%), 0 = exact match
    tier: int = 1
    convert: Callable[[float, str | None], float] | None = None
    plausible: tuple[float, float] | None = None  # sanity range in canonical unit


ATTRS: dict[str, Attr] = {
    a.key: a
    for a in [
        Attr("max_power", "Max power", "kW", "number", "specs", 0.02, convert=units.power_to_kw, plausible=(30, 1500)),
        Attr(
            "max_torque", "Max torque", "N·m", "number", "specs", 0.02, convert=units.torque_to_nm, plausible=(60, 2500)
        ),
        Attr(
            "curb_mass", "Curb weight", "kg", "number", "specs", 0.03, convert=units.mass_to_kg, plausible=(700, 3500)
        ),
        Attr("drivetrain", "Drivetrain", None, "text", "specs", 0),
        Attr("transmission", "Transmission", None, "text", "specs", 0),
        Attr("engine", "Engine / motor", None, "text", "specs", 0),
        Attr(
            "displacement",
            "Displacement",
            "cm³",
            "number",
            "specs",
            0.02,
            convert=units.volume_to_cc,
            plausible=(600, 8500),
        ),
        Attr(
            "battery_kwh",
            "Battery (usable)",
            "kWh",
            "number",
            "specs",
            0.03,
            convert=converters.kwh,
            plausible=(0.2, 150),
        ),
        # spec 006: electric facts (data-model §1). Gross capacity, ranges, kWh/100 km, the plug-in's
        # charge-sustaining and weighted figures (the weighted one is shown, never priced), charging.
        Attr(
            "battery_gross_kwh",
            "Battery (gross)",
            "kWh",
            "number",
            "specs",
            0.03,
            convert=converters.kwh,
            plausible=(0.2, 160),
        ),
        Attr("battery_chemistry", "Battery chemistry", None, "text", "specs", 0),
        Attr(
            "range_wltp",
            "Electric range (WLTP)",
            "km",
            "number",
            "specs",
            0.03,
            convert=converters.km,
            plausible=(15, 1000),
        ),
        Attr(
            "consumption_ev",
            "Electric consumption (WLTP)",
            "kWh/100 km",
            "number",
            "specs",
            0.05,
            convert=converters.kwh100,
            plausible=(8, 40),
        ),
        # chat 2026-11-06 (Deepal S09 vs Li L9): a car sold only in China states the Chinese CLTC cycle, more
        # optimistic than WLTP — its own attributes, never filed or shown as WLTP; the energy model applies its own
        # real-use allowance (config/rates.yaml real_world_factor.CLTC)
        Attr(
            "range_cltc",
            "Electric range (CLTC, China)",
            "km",
            "number",
            "specs",
            0.03,
            convert=converters.km,
            plausible=(15, 1200),
        ),
        Attr(
            "consumption_ev_cltc",
            "Electric consumption (CLTC, China)",
            "kWh/100 km",
            "number",
            "specs",
            0.05,
            convert=converters.kwh100,
            plausible=(8, 40),
        ),
        Attr(
            "consumption_cs",
            "Consumption with an empty battery",
            "l/100 km",
            "number",
            "specs",
            0.05,
            convert=converters.l100,
            plausible=(3, 15),
        ),
        Attr(
            "consumption_weighted",
            "Consumption (WLTP weighted, plug-in)",
            "l/100 km",
            "number",
            "specs",
            0.05,
            convert=converters.l100,
            plausible=(0.1, 3.5),
        ),
        Attr(
            "charge_ac_kw",
            "AC charging power",
            "kW",
            "number",
            "specs",
            0.03,
            convert=converters.kw,
            plausible=(1.8, 22),
        ),
        Attr(
            "charge_dc_peak_kw",
            "DC fast charging (peak)",
            "kW",
            "number",
            "specs",
            0.03,
            convert=converters.kw,
            plausible=(10, 500),
        ),
        Attr(
            "charge_dc_10_80_min",
            "DC 10–80 % time",
            "min",
            "number",
            "specs",
            0.05,
            convert=converters.minutes,
            plausible=(10, 120),
        ),
        Attr("heat_pump", "Heat pump", None, "text", "specs", 0),
        Attr(
            "claimed_0_100",
            "0–100 km/h (claimed)",
            "s",
            "number",
            "specs",
            0.035,
            convert=converters.seconds,
            plausible=(1.8, 25),
        ),
        Attr(
            "top_speed", "Top speed", "km/h", "number", "specs", 0.02, convert=units.speed_to_kmh, plausible=(100, 420)
        ),
        Attr(
            "consumption",
            "Consumption (WLTP comb., official)",
            None,
            "number",
            "specs",
            0.05,
            convert=converters.consumption,
            plausible=(1, 40),
        ),
        # older NEDC homologation figure (≈20–25% below WLTP) and real-world consumption (tests, owners):
        # separate attributes, never compared with WLTP (spec 004 FR-027; user report 2026-11-02, Prado 7.4 NEDC)
        Attr(
            "consumption_nedc",
            "Consumption (NEDC, old cycle)",
            None,
            "number",
            "specs",
            0.05,
            convert=converters.consumption,
            plausible=(1, 40),
        ),
        Attr(
            "consumption_real",
            "Consumption (real-world)",
            None,
            "number",
            "measured",
            0.10,
            tier=3,
            convert=converters.consumption,
            plausible=(1, 45),
        ),
        Attr(
            "range_real",
            "Electric range (real-world)",
            "km",
            "number",
            "measured",
            0.10,
            tier=3,
            convert=converters.km,
            plausible=(10, 1000),
        ),
        Attr(
            "consumption_ev_real",
            "Electric consumption (real-world)",
            "kWh/100 km",
            "number",
            "measured",
            0.10,
            tier=3,
            convert=converters.kwh100,
            plausible=(8, 50),
        ),
        Attr(
            "consumption_ev_plug",
            "Electric consumption (real-world, at the plug)",
            "kWh/100 km",
            "number",
            "measured",
            0.10,
            tier=3,
            convert=converters.kwh100,
            plausible=(8, 50),
        ),
        Attr(
            "boot_volume", "Boot volume", "L", "number", "specs", 0.05, convert=converters.litres, plausible=(50, 2500)
        ),
        Attr("seats", "Seats", None, "number", "specs", 0, convert=converters.same, plausible=(2, 9)),
        Attr(
            "official_price_es",
            "Official price ES (PVP)",
            "EUR",
            "number",
            "price",
            0.03,
            convert=converters.same,
            plausible=(8000, 500000),
        ),
        Attr(
            "service_interval_km",
            "Service interval",
            "km",
            "number",
            "maintenance",
            0,
            convert=units.distance_to_km,
            plausible=(5000, 60000),
        ),
        Attr(
            "service_interval_months",
            "Service interval",
            "months",
            "number",
            "maintenance",
            0,
            convert=converters.same,
            plausible=(6, 48),
        ),
        # practicality / buyer (Tier 1)
        Attr(
            "ground_clearance",
            "Ground clearance",
            "mm",
            "number",
            "specs",
            0.05,
            convert=converters.mm,
            plausible=(90, 400),
        ),
        Attr(
            "rear_legroom", "Rear legroom", "mm", "number", "specs", 0.05, convert=converters.mm, plausible=(600, 1300)
        ),
        Attr("low_range", "Low-range gearbox", None, "text", "specs", 0),
        Attr("tyre_size", "Tyre size", None, "text", "specs", 0),
        Attr(
            "fiscal_hp",
            "Fiscal horsepower (CVF)",
            "CVF",
            "number",
            "specs",
            0.02,
            convert=converters.same,
            plausible=(4, 80),
        ),
        Attr("euro_ncap_stars", "Euro NCAP", "stars", "number", "specs", 0, convert=converters.count, plausible=(0, 5)),
        # stars of different protocol years are not comparable (5★ 2015 ≠ 5★ 2024): the rating year is kept
        Attr(
            "euro_ncap_year",
            "Euro NCAP rating year",
            "year",
            "number",
            "specs",
            0,
            convert=converters.count,
            plausible=(2009, 2035),
        ),  # fmt: skip
        Attr("segment", "Segment", None, "text", "specs", 0),
        # engineering (Tier 2)
        Attr("engine_layout", "Engine layout", None, "text", "engineering", 0, tier=2),
        Attr(
            "cylinders",
            "Cylinders",
            None,
            "number",
            "engineering",
            0,
            tier=2,
            convert=converters.count,
            plausible=(0, 16),
        ),
        Attr("aspiration", "Aspiration", None, "text", "engineering", 0, tier=2),
        Attr("bore", "Bore", "mm", "number", "engineering", 0.01, tier=2, convert=converters.mm, plausible=(50, 120)),
        Attr(
            "stroke", "Stroke", "mm", "number", "engineering", 0.01, tier=2, convert=converters.mm, plausible=(40, 120)
        ),
        Attr(
            "compression_ratio",
            "Compression ratio",
            ":1",
            "number",
            "engineering",
            0.01,
            tier=2,
            convert=converters.same,
            plausible=(6, 25),
        ),  # fmt: skip
        Attr(
            "gear_count", "Gears", None, "number", "engineering", 0, tier=2, convert=converters.count, plausible=(1, 10)
        ),
        Attr("platform", "Platform", None, "text", "engineering", 0, tier=2),
        Attr("suspension_front", "Front suspension", None, "text", "engineering", 0, tier=2),
        Attr("suspension_rear", "Rear suspension", None, "text", "engineering", 0, tier=2),
        # spec 004 FR-007: what changed between model years (facelift, engine change, recall fixed), with the year
        Attr("model_year_changes", "Model-year changes", None, "text", "engineering", 0, tier=2),
        Attr(
            "drag_coefficient",
            "Drag coefficient (Cd)",
            None,
            "number",
            "engineering",
            0.03,
            tier=2,
            convert=converters.same,
            plausible=(0.18, 0.6),
        ),  # fmt: skip
        # measured (Tier 3, instrumented tests only)
        Attr(
            "measured_0_100",
            "0–100 km/h (measured)",
            "s",
            "number",
            "measured",
            0.035,
            tier=3,
            convert=converters.seconds,
            plausible=(1.8, 25),
        ),  # fmt: skip
    ]
}
