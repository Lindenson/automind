"""Deterministic unit parsing and conversion (constitution III). No external dependencies."""

from __future__ import annotations

import re

HP_W = 745.69987  # mechanical horsepower
PS_W = 735.49875  # metric horsepower (PS, CV, ch, pk)
LBFT_NM = 1.3558179483
LB_KG = 0.45359237
MPH_KMH = 1.609344
KGM_NM = 9.80665
MILE_KM = 1.609344
MPG_UK_L100 = 282.481  # l/100 km = 282.481 / imperial mpg
MPG_US_L100 = 235.215  # l/100 km = 235.215 / US mpg

_NUM = re.compile(r"[-+]?\d[\d.,\s]*")


class UnitError(ValueError):
    pass


def _number_text(raw: str) -> re.Match[str] | None:
    return _NUM.search(raw.replace("\u00a0", " ").replace("\u202f", " "))


def _clean(m: re.Match[str]) -> str:
    return m.group(0).strip().replace(" ", "").rstrip(".,")


def parse_number(raw: str) -> float:
    """Parse the first number in a string, handling '1.234,5', '1,234.5', '1 234' formats.

    Ranges like '5000-6500' return the first number. A single separator followed by exactly three digits
    ('1,598', '1.430') is ambiguous: see `number_readings` for both readings.
    """
    m = _number_text(raw)
    if not m:
        raise UnitError(f"no number in {raw!r}")
    s = _clean(m)
    if "," in s and "." in s:
        decimal_comma = s.rfind(",") > s.rfind(".")  # 1.234,5 vs 1,234.5
        s = s.replace(".", "").replace(",", ".") if decimal_comma else s.replace(",", "")
    elif "," in s:
        head, _, tail = s.rpartition(",")
        s = s.replace(",", "") if len(tail) == 3 and head else s.replace(",", ".")
    elif s.count(".") > 1:
        s = s.replace(".", "")
    # one '.': decimal here ('6.2' s); '1.430' kg is resolved by the attribute's range (number_readings)
    return float(s)


def number_readings(raw: str) -> list[float]:
    """`parse_number` first, then the other reading of an ambiguous separator: '1,598' → [1598, 1.598],
    '1.430' → [1.43, 1430]. Callers keep the first reading that fits the attribute's plausible range."""
    first = parse_number(raw)
    m = _number_text(raw)
    s = _clean(m) if m else ""
    seps = [c for c in s if c in ",."]
    if len(seps) == 1:
        head, _, tail = s.partition(seps[0])
        if head.lstrip("+-") and len(head.lstrip("+-")) <= 3 and len(tail) == 3:
            other = float(head + tail) if first != float(head + tail) else float(f"{head}.{tail}")
            return [first, other]
    return [first]


# a unit written right after the first number of a raw value or an excerpt (3.3); vocabulary only,
# so words after the number ("150 a 6000 rpm") are not taken for units
_UNIT_AFTER = re.compile(
    r"""\s*(
      mpg\s*\(?\s*(?:us|u\.s\.|uk|imp(?:erial)?)\.?\s*\)? | (?:us|u\.s\.|uk|imp(?:erial)?)\s+mpg | mpg
    | l\s*/\s*100\s*kms? | kwh\s*/\s*100\s*kms? | km/h | kmh | kph | mph
    | kw | ps | cv | ch | pk | bhp | whp | hp
    | n\s*[·.\-]?\s*m | lb[\s.\-]*ft | ft[\s.\-]*lbs? | kgm
    | kgs? | lbs? | tonnes? | t
    | cc | cm3 | cm³ | ccm | litros? | litres? | liters? | l
    | mm | cm | inch(?:es)? | in | "
    | kms? | kil[oó]met(?:re|er|ro)s? | miles(?!\s+de\b) | mile | mi
    | secs? | seconds? | seg(?:undos)? | s
    )(?![a-z0-9áéíóú])""",
    re.X | re.I,
)


def unit_after(text: str, pos: int) -> str | None:
    """The unit written at `pos` (just after a number), or None."""
    m = _UNIT_AFTER.match(text, pos)
    return m.group(1) if m else None


def unit_in(raw: str) -> str | None:
    """The unit written after the first number of `raw` ('20 000 miles' → 'miles'), or None."""
    t = raw.replace("\u00a0", " ").replace("\u202f", " ")
    m = _NUM.search(t)
    if not m:
        return None
    end = m.start() + len(m.group(0).rstrip())
    return unit_after(t, end)


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
    if u in ("nm", "n-m", "n.m", "newtonmetre", "newtonmeter", "newtonmetres", "newtonmeters"):
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
    if u in ("l", "litre", "liter", "litres", "liters", "litro", "litros"):
        return value * 1000
    raise UnitError(f"unknown displacement unit {unit!r}")


def distance_to_km(value: float, unit: str | None) -> float:
    u = _u(unit)
    if u in ("km", "kms", "kilometre", "kilometres", "kilometer", "kilometers", "kilómetro", "kilómetros",
             "kilometro", "kilometros", ""):  # fmt: skip
        return value
    if u in ("mi", "mile", "miles"):
        return value * MILE_KM
    raise UnitError(f"unknown distance unit {unit!r}")


def mpg_market(unit: str | None, domain: str | None = None, excerpt: str | None = None) -> str:
    """'US' or 'UK' gallons for an mpg figure: the unit text first ('mpg (US)', 'imp'), then the excerpt
    ('EPA', 'US mpg'), then the source domain (.uk/.ie → UK; .us, .gov or a known US publication → US).
    Unknown → UK: the English-language sources relevant to EU buyers are mostly British (imperial mpg)."""
    u = _u(unit)
    if re.search(r"\bus\b|u\.s\.|us\)|^us|mpgus", u):
        return "US"
    if "imp" in u or "uk" in u:
        return "UK"
    ex = (excerpt or "").lower()
    if re.search(r"\b(?:epa|u\.?s\.? mpg|mpg \(?us\b)", ex):
        return "US"
    if re.search(r"\b(?:imperial|uk mpg|mpg \(?(?:uk|imp))", ex):
        return "UK"
    host = (domain or "").lower().strip()
    if "://" in host:
        host = host.split("://", 1)[1]
    host = host.split("/", 1)[0].split(":", 1)[0].removeprefix("www.")
    if host.endswith((".uk", ".ie")):
        return "UK"
    if host.endswith((".us", ".gov")) or any(host == d or host.endswith("." + d) for d in US_PUBLICATIONS):
        return "US"
    return "UK"


US_PUBLICATIONS = (
    "caranddriver.com", "motortrend.com", "edmunds.com", "cars.com", "kbb.com", "roadandtrack.com",
    "consumerreports.org", "autoblog.com", "thecarconnection.com", "jdpower.com", "autotrader.com", "carfax.com",
    "truecar.com", "cargurus.com", "automobilemag.com", "fueleconomy.gov", "iihs.org", "usnews.com", "jalopnik.com",
)  # fmt: skip


def mpg_to_l100km(value: float, market: str) -> float:
    if value <= 0:
        raise UnitError(f"mpg must be positive: {value}")
    return (MPG_US_L100 if market == "US" else MPG_UK_L100) / value


def kw_to_hp_display(kw: float) -> str:
    return f"{kw:.0f} kW ({kw * 1000 / PS_W:.0f} PS)"
