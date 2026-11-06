"""Unit converters of the attribute registry: a raw number and its unit to the attribute canonical unit (seconds, l/100
km, kWh, kW, km, mm ...)."""

from __future__ import annotations

from automind.shared.vehicle import units


def same(v: float, _u: str | None) -> float:
    return v


def seconds(v: float, u: str | None) -> float:
    if (u or "s").strip().lower() not in ("s", "sec", "secs", "seconds", "seg", "segundos", "秒"):
        raise units.UnitError(f"unknown time unit {u!r}")
    return v


def consumption(v: float, u: str | None) -> float:
    """l/100 km or kWh/100 km; mpg is converted to l/100 km ('mpg (US)' → US gallons, other mpg → imperial)."""
    unit = (u or "").strip().lower().replace(" ", "")
    if "mpg" in unit:
        return units.mpg_to_l100km(v, units.mpg_market(u))
    if unit not in ("l/100km", "l/100", "kwh/100km", "kwh/100", "l/100kms"):
        raise units.UnitError(f"consumption unit {u!r} not accepted (need l/100 km or kWh/100 km)")
    return v


def kwh(v: float, u: str | None) -> float:
    """Energy (battery capacity): kWh only; a kW figure is power, not capacity (spec 006 FR-007)."""
    unit = (u or "kwh").strip().lower().replace(" ", "")
    if unit not in ("kwh", "kw·h", "kw-h"):
        raise units.UnitError(f"energy needs kWh, got {u!r} (kW is power)")
    return v


def kw(v: float, u: str | None) -> float:
    """Charging power: kW only; a kWh figure is energy, not power (spec 006 FR-007)."""
    unit = (u or "kw").strip().lower().replace(" ", "")
    if unit != "kw":
        raise units.UnitError(f"power needs kW, got {u!r} (kWh is energy)")
    return v


def kwh100(v: float, u: str | None) -> float:
    unit = (u or "").strip().lower().replace(" ", "")
    if unit in ("kwh/100km", "kwh/100", "kwh/100kms", "千瓦时/百公里", "kwh/百公里", "度/百公里"):
        return v
    if unit in ("wh/km",):
        return v / 10
    raise units.UnitError(f"electric consumption needs kWh/100 km, got {u!r}")


def l100(v: float, u: str | None) -> float:
    unit = (u or "").strip().lower().replace(" ", "")
    if "mpg" in unit:
        return units.mpg_to_l100km(v, units.mpg_market(u))
    if unit not in ("l/100km", "l/100", "l/100kms", "升/百公里", "l/百公里"):
        raise units.UnitError(f"fuel consumption needs l/100 km, got {u!r}")
    return v


def km(v: float, u: str | None) -> float:
    unit = (u or "km").strip().lower()
    if unit in ("km", "kms", "kilómetros", "kilometros", "kilometres", "kilometers", "км", "公里", "千米"):
        return v
    if unit in ("mi", "miles", "mile", "millas"):
        return v * 1.609344
    raise units.UnitError(f"distance needs km, got {u!r}")


def minutes(v: float, u: str | None) -> float:
    unit = (u or "min").strip().lower()
    if unit in ("min", "mins", "minutes", "minutos", "мин", "minuten"):
        return v
    if unit in ("h", "hours", "horas", "ч"):
        return v * 60
    raise units.UnitError(f"time needs minutes, got {u!r}")


def mm(v: float, u: str | None) -> float:
    unit = (u or "mm").strip().lower()
    if unit in ("mm", "millimetres", "millimeters", "milímetros"):
        return v
    if unit in ("cm", "centimetres", "centimeters"):
        return v * 10
    if unit in ("in", "inch", "inches", '"'):
        return v * 25.4
    raise units.UnitError(f"unknown length unit {u!r}")


def count(v: float, u: str | None) -> float:
    if v != int(v):
        raise units.UnitError(f"count must be whole: {v}")
    return v


def litres(v: float, u: str | None) -> float:
    if (u or "l").strip().lower() not in ("l", "litre", "liter", "litres", "liters", "litros", "dm3"):
        raise units.UnitError(f"unknown volume unit {u!r}")
    return v
