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
    if (u or "s").strip().lower() not in ("s", "sec", "secs", "seconds", "seg", "segundos", "秒"):
        raise units.UnitError(f"unknown time unit {u!r}")
    return v


def _consumption(v: float, u: str | None) -> float:
    """l/100 km or kWh/100 km; mpg is converted to l/100 km ('mpg (US)' → US gallons, other mpg → imperial)."""
    unit = (u or "").strip().lower().replace(" ", "")
    if "mpg" in unit:
        return units.mpg_to_l100km(v, units.mpg_market(u))
    if unit not in ("l/100km", "l/100", "kwh/100km", "kwh/100", "l/100kms"):
        raise units.UnitError(f"consumption unit {u!r} not accepted (need l/100 km or kWh/100 km)")
    return v


def _kwh(v: float, u: str | None) -> float:
    """Energy (battery capacity): kWh only; a kW figure is power, not capacity (spec 006 FR-007)."""
    unit = (u or "kwh").strip().lower().replace(" ", "")
    if unit not in ("kwh", "kw·h", "kw-h"):
        raise units.UnitError(f"energy needs kWh, got {u!r} (kW is power)")
    return v


def _kw(v: float, u: str | None) -> float:
    """Charging power: kW only; a kWh figure is energy, not power (spec 006 FR-007)."""
    unit = (u or "kw").strip().lower().replace(" ", "")
    if unit != "kw":
        raise units.UnitError(f"power needs kW, got {u!r} (kWh is energy)")
    return v


def _kwh100(v: float, u: str | None) -> float:
    unit = (u or "").strip().lower().replace(" ", "")
    if unit in ("kwh/100km", "kwh/100", "kwh/100kms", "千瓦时/百公里", "kwh/百公里", "度/百公里"):
        return v
    if unit in ("wh/km",):
        return v / 10
    raise units.UnitError(f"electric consumption needs kWh/100 km, got {u!r}")


def _l100(v: float, u: str | None) -> float:
    unit = (u or "").strip().lower().replace(" ", "")
    if "mpg" in unit:
        return units.mpg_to_l100km(v, units.mpg_market(u))
    if unit not in ("l/100km", "l/100", "l/100kms", "升/百公里", "l/百公里"):
        raise units.UnitError(f"fuel consumption needs l/100 km, got {u!r}")
    return v


def _km(v: float, u: str | None) -> float:
    unit = (u or "km").strip().lower()
    if unit in ("km", "kms", "kilómetros", "kilometros", "kilometres", "kilometers", "км", "公里", "千米"):
        return v
    if unit in ("mi", "miles", "mile", "millas"):
        return v * 1.609344
    raise units.UnitError(f"distance needs km, got {u!r}")


def _minutes(v: float, u: str | None) -> float:
    unit = (u or "min").strip().lower()
    if unit in ("min", "mins", "minutes", "minutos", "мин", "minuten"):
        return v
    if unit in ("h", "hours", "horas", "ч"):
        return v * 60
    raise units.UnitError(f"time needs minutes, got {u!r}")


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
        Attr("battery_kwh", "Battery (usable)", "kWh", "number", "specs", 0.03, convert=_kwh, plausible=(0.2, 150)),
        # spec 006: electric facts (data-model §1). Gross capacity, ranges, kWh/100 km, the plug-in's
        # charge-sustaining and weighted figures (the weighted one is shown, never priced), charging.
        Attr(
            "battery_gross_kwh", "Battery (gross)", "kWh", "number", "specs", 0.03, convert=_kwh, plausible=(0.2, 160)
        ),
        Attr("battery_chemistry", "Battery chemistry", None, "text", "specs", 0),
        Attr("range_wltp", "Electric range (WLTP)", "km", "number", "specs", 0.03, convert=_km, plausible=(15, 1000)),
        Attr(
            "consumption_ev",
            "Electric consumption (WLTP)",
            "kWh/100 km",
            "number",
            "specs",
            0.05,
            convert=_kwh100,
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
            convert=_km,
            plausible=(15, 1200),
        ),
        Attr(
            "consumption_ev_cltc",
            "Electric consumption (CLTC, China)",
            "kWh/100 km",
            "number",
            "specs",
            0.05,
            convert=_kwh100,
            plausible=(8, 40),
        ),
        Attr(
            "consumption_cs",
            "Consumption with an empty battery",
            "l/100 km",
            "number",
            "specs",
            0.05,
            convert=_l100,
            plausible=(3, 15),
        ),
        Attr(
            "consumption_weighted",
            "Consumption (WLTP weighted, plug-in)",
            "l/100 km",
            "number",
            "specs",
            0.05,
            convert=_l100,
            plausible=(0.1, 3.5),
        ),
        Attr("charge_ac_kw", "AC charging power", "kW", "number", "specs", 0.03, convert=_kw, plausible=(1.8, 22)),
        Attr(
            "charge_dc_peak_kw",
            "DC fast charging (peak)",
            "kW",
            "number",
            "specs",
            0.03,
            convert=_kw,
            plausible=(10, 500),
        ),
        Attr(
            "charge_dc_10_80_min",
            "DC 10–80 % time",
            "min",
            "number",
            "specs",
            0.05,
            convert=_minutes,
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
            convert=_seconds,
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
            convert=_consumption,
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
            convert=_consumption,
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
            convert=_consumption,
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
            convert=_km,
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
            convert=_kwh100,
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
            convert=_kwh100,
            plausible=(8, 50),
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
        # stars of different protocol years are not comparable (5★ 2015 ≠ 5★ 2024): the rating year is kept
        Attr(
            "euro_ncap_year",
            "Euro NCAP rating year",
            "year",
            "number",
            "specs",
            0,
            convert=_count,
            plausible=(2009, 2035),
        ),  # fmt: skip
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


_GEARS = {"four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "cuatro": 4, "cinco": 5,
          "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10}  # fmt: skip


def normalize_transmission(raw: str) -> str | None:
    """Canonical gearbox text. Spec sites list hybrid planetary e-CVTs and BEV reductions as "1 speed": that is
    not a one-speed gearbox, so the speed count is dropped for those (user report 2026-11-02)."""
    r = " " + raw.lower().replace("-", " ") + " "
    m = re.search(r"(\d{1,2})\s*(?:speed|velocidades|relaciones|marchas|gang|vel)", r)
    n = int(m.group(1)) if m else next((v for k, v in _GEARS.items() if f" {k} " in r or f" {k}speed" in r), None)
    if any(k in r for k in ("e cvt", "ecvt", "power split", "planetary", "planetario", "e:hev", "hybrid synergy")):
        return "e-CVT (power-split hybrid)"
    if any(k in r for k in ("cvt", "continuously variable", "variador", "variable continua", "stufenlos")):
        return "CVT"
    if any(k in r for k in ("single speed", "single ratio", "reduction", "reductora fija", "1 speed direct")):
        return "single-speed reduction"
    if any(k in r for k in ("dct", "dsg", "dual clutch", "doble embrague", "doppelkupplung", "edc", "s tronic")):
        return f"dual-clutch {n}-speed" if n and n > 1 else "dual-clutch"
    if any(k in r for k in ("manual", "manuell", "mt ")):
        return f"manual {n}-speed" if n and n > 1 else "manual"
    if any(k in r for k in ("auto", "steptronic", "tiptronic", "automática", "automatica", "at ", "torque converter")):
        return f"automatic {n}-speed" if n and n > 1 else "automatic"
    return None


def _low_range(raw_value: str) -> str:
    r = raw_value.strip().lower()
    if any(k in r for k in ("no ", "without", "sin ", "none")) or r in ("no", "n/a"):
        return "NO"
    if any(k in r for k in ("low range", "low-range", "reductora", "yes", "transfer", "2-speed", "hi/lo")):
        return "YES"
    raise units.UnitError(f"unrecognized low range value {raw_value!r}")


def _normalize_text(key: str, raw_value: str) -> str:
    if key == "drivetrain":
        d = normalize_drivetrain(raw_value)
        if d is None:
            raise units.UnitError(f"unrecognized drivetrain {raw_value!r}")
        return d
    if key == "low_range":
        return _low_range(raw_value)
    if key == "transmission":
        t = normalize_transmission(raw_value)
        if t is None:
            raise units.UnitError(f"unrecognized transmission {raw_value!r}")
        return t
    return raw_value.strip()


_SEATS_SUM = re.compile(r"(?<![\d.,])(\d)\s*\+\s*(\d)(?![\d.,])")  # '5+2' = 7 seats
_SEATS_ALT = re.compile(r"(?<![\d.,])(\d)\s*/\s*(\d)(?![\d.,])")  # '5/7' = up to 7 seats


def _seats(raw_value: str) -> float | None:
    if m := _SEATS_SUM.search(raw_value):
        return float(int(m.group(1)) + int(m.group(2)))
    if m := _SEATS_ALT.search(raw_value):
        return float(max(int(m.group(1)), int(m.group(2))))
    return None


def _excerpt_unit(raw_value: str, excerpt: str | None) -> str | None:
    """The unit written after the raw value where the excerpt quotes it ('150' in '... 150 CV a 6000 rpm')."""
    if not excerpt:
        return None
    ex = excerpt.replace("\u00a0", " ").replace("\u202f", " ")
    raw = raw_value.strip()
    i = ex.lower().find(raw.lower()) if raw else -1
    if i >= 0 and (i == 0 or not ex[i - 1].isdigit()) and not ex[i + len(raw) : i + len(raw) + 1].isdigit():
        return units.unit_in(ex[i:])
    num = re.match(r"[-+]?\d[\d.,\s]*", raw)
    if num is None:
        return None
    n = num.group(0).strip().rstrip(".,")
    for m in re.finditer(r"(?<![\d.,])" + re.escape(n) + r"(?![\d])", ex):
        return units.unit_after(ex, m.end())
    return None


def _mpg_unit(unit: str, domain: str | None, excerpt: str | None) -> str:
    return f"mpg ({units.mpg_market(unit, domain, excerpt)})" if "mpg" in unit.lower() else unit


def normalize(
    attr: Attr, raw_value: str, unit: str | None, *, excerpt: str | None = None, domain: str | None = None
) -> float | str:
    """Convert a raw extracted value to the canonical unit. Raises UnitError when impossible.

    The unit is taken from the raw value when written there ('20 000 miles', '150 hp': the raw value is the
    page text, the `unit` field only the model's reading of it), else `unit`, else the unit after the value in
    `excerpt`. An ambiguous separator ('1,598' l, '1.430' kg) takes the reading inside the plausible range.
    `domain` (host or URL of the source) only decides US vs imperial mpg (see `units.mpg_market`).
    """
    if attr.kind == "text":
        return _normalize_text(attr.key, raw_value)
    assert attr.convert is not None
    seats = _seats(raw_value) if attr.key == "seats" else None
    if seats is None and RANGE_RE.search(raw_value):
        raise units.UnitError(f"{attr.key}: range {raw_value!r} is not a single variant value")
    readings = [seats] if seats is not None else units.number_readings(raw_value)
    lo = attr.plausible[0] if attr.plausible else None
    # European thousands separator lost in the unit field: '1.6' with unit cc, '1.43' kg (kept from before)
    if lo is not None and readings[0] < lo <= readings[0] * 1000 and "." in raw_value:
        readings.append(readings[0] * 1000)
    in_raw = units.unit_in(raw_value)
    in_excerpt = _excerpt_unit(raw_value, excerpt) if in_raw is None else None
    candidates = [in_raw, unit, in_excerpt] if unit else [in_raw, in_excerpt, unit]
    tried: list[str | None] = []
    err: units.UnitError | None = None
    for u in candidates:
        if u is None and (in_raw or in_excerpt or unit) or u in tried:
            continue  # no unit is a candidate only when nothing names one
        tried.append(u)
        u2 = _mpg_unit(u, domain, excerpt) if u else u
        try:
            outs = [attr.convert(v, u2) for v in readings]
        except units.UnitError as e:
            err = e
            continue
        if attr.plausible:
            lo_, hi = attr.plausible
            fit = next((o for o in outs if lo_ <= o <= hi), None)
            if fit is None:
                raise units.UnitError(f"{attr.key}={outs[0]} outside plausible range {attr.plausible}")
            return round(fit, 3)
        return round(outs[0], 3)
    raise err or units.UnitError(f"{attr.key}: no unit for {raw_value!r}")
