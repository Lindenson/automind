"""Deterministic unit parsing and conversion (constitution III). No external dependencies."""

from __future__ import annotations

import re

HP_W = 745.69987  # mechanical horsepower
PS_W = 735.49875  # metric horsepower (PS, CV, ch, pk)
LBFT_NM = 1.3558179483
LB_KG = 0.45359237
MPH_KMH = 1.609344
KGM_NM = 9.80665

_NUM = re.compile(r"[-+]?\d[\d.,\s]*")


class UnitError(ValueError):
    pass


def parse_number(raw: str) -> float:
    """Parse the first number in a string, handling '1.234,5', '1,234.5', '1 234' formats.

    Ranges like '5000-6500' return the first number.
    """
    m = _NUM.search(raw.replace(" ", " ").replace(" ", " "))
    if not m:
        raise UnitError(f"no number in {raw!r}")
    s = m.group(0).strip().replace(" ", "")
    s = s.rstrip(".,")
    if "," in s and "." in s:
        decimal_comma = s.rfind(",") > s.rfind(".")  # 1.234,5 vs 1,234.5
        s = s.replace(".", "").replace(",", ".") if decimal_comma else s.replace(",", "")
    elif "," in s:
        head, _, tail = s.rpartition(",")
        s = s.replace(",", "") if len(tail) == 3 and head else s.replace(",", ".")
    elif s.count(".") == 1:
        head, _, tail = s.partition(".")
        # '1.430' (kg in European notation) vs '6.2' (seconds): thousands sep if exactly 3 digits
        # and the integer part is short. Callers pass hints via unit context; keep decimal here
        # unless the value would be implausibly small for mass/price (handled in normalize()).
    elif s.count(".") > 1:
        s = s.replace(".", "")
    return float(s)


def _u(unit: str | None) -> str:
    return (unit or "").strip().lower().replace(" ", "").replace("·", "")


def power_to_kw(value: float, unit: str | None) -> float:
    u = _u(unit)
    if u in ("kw", "kilowatt", "kilowatts"):
        return value
    if u in ("ps", "cv", "ch", "pk", "metrichp", "hp(metric)"):
        return value * PS_W / 1000
    if u in ("hp", "bhp", "whp"):
        return value * HP_W / 1000
    raise UnitError(f"unknown power unit {unit!r}")


def torque_to_nm(value: float, unit: str | None) -> float:
    u = _u(unit)
    if u in ("nm", "n-m", "newtonmetre", "newtonmeter", "newtonmetres", "newtonmeters"):
        return value
    if u in ("lb-ft", "lbft", "lb.ft", "lbf-ft", "lbfft", "ft-lb", "ftlb", "pound-feet"):
        return value * LBFT_NM
    if u in ("kgm", "kgfm", "mkg"):
        return value * KGM_NM
    raise UnitError(f"unknown torque unit {unit!r}")


def mass_to_kg(value: float, unit: str | None) -> float:
    u = _u(unit)
    if u in ("kg", "kgs", "kilogram", "kilograms", ""):
        return value
    if u in ("lb", "lbs", "pound", "pounds"):
        return value * LB_KG
    if u in ("t", "tonne", "tonnes"):
        return value * 1000
    raise UnitError(f"unknown mass unit {unit!r}")


def speed_to_kmh(value: float, unit: str | None) -> float:
    u = _u(unit)
    if u in ("km/h", "kmh", "kph", ""):
        return value
    if u == "mph":
        return value * MPH_KMH
    raise UnitError(f"unknown speed unit {unit!r}")


def volume_to_cc(value: float, unit: str | None) -> float:
    u = _u(unit)
    if u in ("cc", "cm3", "cm³", "ccm"):
        return value
    if u in ("l", "litre", "liter", "litres", "liters"):
        return value * 1000
    raise UnitError(f"unknown displacement unit {unit!r}")


def kw_to_hp_display(kw: float) -> str:
    return f"{kw:.0f} kW ({kw * 1000 / PS_W:.0f} PS)"
