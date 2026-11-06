"""Normalising raw values: a cell or excerpt (text, unit, range) to the canonical value of its attribute; drivetrain
and gearbox words to their codes."""

from __future__ import annotations

import re

from automind.shared.vehicle import units
from automind.shared.vehicle.specs.registry import Attr

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
