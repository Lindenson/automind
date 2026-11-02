"""Specification attribute registry: Tier 1 core specs, practicality, Tier 2 engineering, buyer data."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Literal

from . import units

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


def _same(v: float, _u: str | None) -> float:
    return v


def _seconds(v: float, u: str | None) -> float:
    if (u or "s").strip().lower() not in ("s", "sec", "secs", "seconds", "seg", "segundos"):
        raise units.UnitError(f"unknown time unit {u!r}")
    return v


def _consumption(v: float, u: str | None) -> float:
    unit = (u or "").strip().lower().replace(" ", "")
    if unit not in ("l/100km", "l/100", "kwh/100km", "kwh/100", "l/100kms"):
        raise units.UnitError(f"consumption unit {u!r} not accepted (need l/100 km or kWh/100 km)")
    return v


def _mm(v: float, u: str | None) -> float:
    unit = (u or "mm").strip().lower()
    if unit in ("mm", "millimetres", "millimeters", "milímetros"):
        return v
    if unit in ("cm", "centimetres", "centimeters"):
        return v * 10
    if unit in ("in", "inch", "inches", '"'):
        return v * 25.4
    raise units.UnitError(f"unknown length unit {u!r}")


def _count(v: float, u: str | None) -> float:
    if v != int(v):
        raise units.UnitError(f"count must be whole: {v}")
    return v


def _litres(v: float, u: str | None) -> float:
    if (u or "l").strip().lower() not in ("l", "litre", "liter", "litres", "liters", "litros", "dm3"):
        raise units.UnitError(f"unknown volume unit {u!r}")
    return v


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
        Attr("battery_kwh", "Battery (usable)", "kWh", "number", "specs", 0.03, convert=_same, plausible=(5, 150)),
        Attr(
            "claimed_0_100",
            "0–100 km/h (claimed)",
            "s",
            "number",
            "specs",
            0.035,
            convert=_seconds,
            plausible=(1.8, 25),
        ),
        Attr(
            "top_speed", "Top speed", "km/h", "number", "specs", 0.02, convert=units.speed_to_kmh, plausible=(100, 420)
        ),
        Attr(
            "consumption",
            "Consumption (WLTP comb.)",
            None,
            "number",
            "specs",
            0.05,
            convert=_consumption,
            plausible=(1, 40),
        ),
        Attr("boot_volume", "Boot volume", "L", "number", "specs", 0.05, convert=_litres, plausible=(50, 2500)),
        Attr("seats", "Seats", None, "number", "specs", 0, convert=_same, plausible=(2, 9)),
        Attr(
            "official_price_es",
            "Official price ES (PVP)",
            "EUR",
            "number",
            "price",
            0.03,
            convert=_same,
            plausible=(8000, 500000),
        ),
        Attr(
            "service_interval_km",
            "Service interval",
            "km",
            "number",
            "maintenance",
            0,
            convert=_same,
            plausible=(5000, 60000),
        ),
        Attr(
            "service_interval_months",
            "Service interval",
            "months",
            "number",
            "maintenance",
            0,
            convert=_same,
            plausible=(6, 48),
        ),
        # practicality / buyer (Tier 1)
        Attr("ground_clearance", "Ground clearance", "mm", "number", "specs", 0.05, convert=_mm, plausible=(90, 400)),
        Attr("rear_legroom", "Rear legroom", "mm", "number", "specs", 0.05, convert=_mm, plausible=(600, 1300)),
        Attr("low_range", "Low-range gearbox", None, "text", "specs", 0),
        Attr("tyre_size", "Tyre size", None, "text", "specs", 0),
        Attr("fiscal_hp", "Fiscal horsepower (CVF)", "CVF", "number", "specs", 0.02, convert=_same, plausible=(4, 80)),
        Attr("euro_ncap_stars", "Euro NCAP", "stars", "number", "specs", 0, convert=_count, plausible=(0, 5)),
        Attr("segment", "Segment", None, "text", "specs", 0),
        # engineering (Tier 2)
        Attr("engine_layout", "Engine layout", None, "text", "engineering", 0, tier=2),
        Attr("cylinders", "Cylinders", None, "number", "engineering", 0, tier=2, convert=_count, plausible=(0, 16)),
        Attr("aspiration", "Aspiration", None, "text", "engineering", 0, tier=2),
        Attr("bore", "Bore", "mm", "number", "engineering", 0.01, tier=2, convert=_mm, plausible=(50, 120)),
        Attr("stroke", "Stroke", "mm", "number", "engineering", 0.01, tier=2, convert=_mm, plausible=(40, 120)),
        Attr(
            "compression_ratio",
            "Compression ratio",
            ":1",
            "number",
            "engineering",
            0.01,
            tier=2,
            convert=_same,
            plausible=(6, 25),
        ),  # fmt: skip
        Attr("gear_count", "Gears", None, "number", "engineering", 0, tier=2, convert=_count, plausible=(1, 10)),
        Attr("platform", "Platform", None, "text", "engineering", 0, tier=2),
        Attr("suspension_front", "Front suspension", None, "text", "engineering", 0, tier=2),
        Attr("suspension_rear", "Rear suspension", None, "text", "engineering", 0, tier=2),
        Attr(
            "drag_coefficient",
            "Drag coefficient (Cd)",
            None,
            "number",
            "engineering",
            0.03,
            tier=2,
            convert=_same,
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
            convert=_seconds,
            plausible=(1.8, 25),
        ),  # fmt: skip
    ]
}

DRIVETRAINS = {"FWD", "RWD", "AWD"}
# "1381-1502 kg", "13.9–5.1 l": generation-wide ranges, not a variant value
RANGE_RE = re.compile(r"\d[\d.,]*\s*(?:-|–|—|to|a)\s*\d")


def normalize_drivetrain(raw: str) -> str | None:
    r = raw.lower()
    if any(
        k in r
        for k in (
            "awd",
            "4wd",
            "4x4",
            "all-wheel",
            "all wheel",
            "4motion",
            "quattro",
            "xdrive",
            "integral",
            "total",
            "dual motor",
            "4matic",
        )
    ):
        return "AWD"
    if any(k in r for k in ("rwd", "rear-wheel", "rear wheel", "trasera", "propulsión", "propulsion")):
        return "RWD"
    if any(k in r for k in ("fwd", "front-wheel", "front wheel", "delantera", "tracción delantera")):
        return "FWD"
    return None


def normalize(attr: Attr, raw_value: str, unit: str | None) -> float | str:
    """Convert a raw extracted value to the canonical unit. Raises UnitError when impossible."""
    if attr.kind == "text":
        if attr.key == "drivetrain":
            d = normalize_drivetrain(raw_value)
            if d is None:
                raise units.UnitError(f"unrecognized drivetrain {raw_value!r}")
            return d
        if attr.key == "low_range":
            r = raw_value.strip().lower()
            if any(k in r for k in ("no ", "without", "sin ", "none")) or r in ("no", "n/a"):
                return "NO"
            if any(k in r for k in ("low range", "low-range", "reductora", "yes", "transfer", "2-speed", "hi/lo")):
                return "YES"
            raise units.UnitError(f"unrecognized low range value {raw_value!r}")
        return raw_value.strip()
    if RANGE_RE.search(raw_value):
        raise units.UnitError(f"{attr.key}: range {raw_value!r} is not a single variant value")
    v = units.parse_number(raw_value)
    assert attr.convert is not None
    # European thousands separator: '1.430 kg' parsed as 1.43 -> fix for big-magnitude attributes
    if attr.plausible and v < attr.plausible[0] and v * 1000 >= attr.plausible[0] and "." in raw_value:
        v *= 1000
    out = attr.convert(v, unit)
    if attr.plausible and not (attr.plausible[0] <= out <= attr.plausible[1]):
        raise units.UnitError(f"{attr.key}={out} outside plausible range {attr.plausible}")
    return round(out, 3)
