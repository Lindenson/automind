"""Car facts and derived metrics (power-to-weight etc.). Pure and deterministic.

Metrics are physical quantities with units, never scores (scores live in criteria.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field

METRICS_VERSION = "1.0"


@dataclass(frozen=True)
class ReliabilitySummary:
    """Documented issues for a variant (from validated research)."""

    minimum_met: bool
    recurring: int = 0
    isolated: int = 0
    high: int = 0


@dataclass(frozen=True)
class ReviewSummary:
    """Validated review points per tag: (pros, cons). Only recurring points are scored."""

    minimum_met: bool
    recurring: dict[str, tuple[int, int]] = field(default_factory=dict)
    isolated: dict[str, tuple[int, int]] = field(default_factory=dict)
    review_count: int = 0
    source_count: int = 0


@dataclass
class CarFacts:
    car_id: str
    label: str
    powertrain: str
    power_kw: float | None = None
    torque_nm: float | None = None
    mass_kg: float | None = None
    displacement_cc: float | None = None
    drivetrain: str | None = None
    top_speed_kmh: float | None = None
    consumption: float | None = None  # l/100 km (ICE/HEV) or kWh/100 km (BEV)
    boot_l: float | None = None
    seats: float | None = None
    price_eur: float | None = None
    service_interval_km: float | None = None
    service_interval_months: float | None = None
    sim_0_100: float | None = None
    sim_400m: float | None = None
    # practicality, status, off-road (sourced where available)
    rear_legroom_mm: float | None = None
    ground_clearance_mm: float | None = None
    low_range: str | None = None  # YES | NO
    euro_ncap: float | None = None
    vehicle_class: str | None = None  # small | compact | mid_large | premium_suv_4x4
    brand_positioning: str | None = None  # PREMIUM | MAINSTREAM | BUDGET (sourced)
    condition: str = "NEW"
    age_years: int | None = None
    # computed elsewhere
    annual_cost_eur: float | None = None  # ownership cost per year (TCO)
    reliability: ReliabilitySummary | None = None
    reviews: ReviewSummary | None = None
    engineering_completeness: float | None = None  # share of Tier 2 attributes documented (0..1)


def metrics(c: CarFacts) -> dict[str, float | None]:
    t = (c.mass_kg / 1000) if c.mass_kg else None
    return {
        "power_to_weight": round(c.power_kw / t, 1) if c.power_kw and t else None,  # kW/t
        "weight_to_power": round(c.mass_kg / c.power_kw, 2) if c.power_kw and c.mass_kg else None,  # kg/kW
        "torque_to_weight": round(c.torque_nm / t, 1) if c.torque_nm and t else None,  # N·m/t
        "specific_output": round(c.power_kw / (c.displacement_cc / 1000), 1)
        if c.power_kw and c.displacement_cc and c.powertrain != "BEV"
        else None,  # kW/L
    }


def lin(x: float | None, lo: float, hi: float) -> float | None:
    """Map x linearly so that lo -> 0 and hi -> 100 (works for 'lower is better' with lo > hi)."""
    if x is None:
        return None
    return round(max(0.0, min(100.0, (x - lo) / (hi - lo) * 100)), 1)
