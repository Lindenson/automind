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
    euro_ncap_year: float | None = None
    vehicle_class: str | None = None  # small | compact | mid_large | premium_suv_4x4
    brand_positioning: str | None = None  # PREMIUM | MAINSTREAM | BUDGET (sourced)
    condition: str = "NEW"
    age_years: int | None = None
    # computed elsewhere
    annual_cost_eur: float | None = None  # ownership cost per year (TCO)
    energy_eur_per_100km: float | None = None  # energy cost per 100 km at the user's prices (spec 006 FR-023)
    reliability: ReliabilitySummary | None = None
    reviews: ReviewSummary | None = None
    engineering_completeness: float | None = None  # share of Tier 2 attributes documented (0..1)
    # on sale for less than NEW_GENERATION_YEARS: no reliability history can exist yet (live chat 4978a3de)
    new_generation_since: int | None = None


NEW_GENERATION_YEARS = 2


def new_generation_since(generation_from: int | None, year: int | None) -> int | None:
    """The first sale year of a generation younger than NEW_GENERATION_YEARS, else None."""
    if generation_from is None or year is None:
        return None
    return generation_from if 0 <= year - generation_from < NEW_GENERATION_YEARS else None


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


# --- spec 005 R13: intake quality ----------------------------------------------------------------------------


def intake_summary(events: list[tuple[str, str, dict[str, object]]]) -> dict[str, object]:
    """From (chat_id, kind, details) in time order: user replies until the identity was confirmed (median per
    chat), questions repeated word for word, corrections that changed a car, research started on an unconfirmed
    car (must stay 0), and the share of chats confirmed within 3 replies (SC-002)."""
    replies: dict[str, int] = {}
    confirmed: dict[str, int] = {}
    repeated = corrected = unconfirmed = 0
    for chat, kind, details in events:
        if kind == "ANSWERED" and chat not in confirmed:
            replies[chat] = replies.get(chat, 0) + 1
        elif kind == "CONFIRMED" and chat not in confirmed:
            confirmed[chat] = replies.get(chat, 0)
        elif kind == "ASKED" and details.get("repeat"):
            repeated += 1
        elif kind == "CORRECTED":
            corrected += 1
        elif kind == "RESEARCH_STARTED" and not details.get("all_confirmed", True):
            unconfirmed += 1
    counts = sorted(confirmed.values())
    median = counts[len(counts) // 2] if counts else None
    within = round(sum(1 for n in counts if n <= 3) / len(counts), 3) if counts else None
    return {"chats_confirmed": len(counts), "replies_to_confirmed_median": median, "confirmed_within_3": within,
            "repeated_questions": repeated, "corrections": corrected, "research_unconfirmed": unconfirmed}  # fmt: skip
