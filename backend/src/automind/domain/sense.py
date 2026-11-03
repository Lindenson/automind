"""Sense checks: does a value mean what its attribute means? (spec 004 FR-027; research R4). Pure.

Runs next to unit normalisation and plausibility (003). Excerpt checks prove that a text exists; these rules
check that the value is the right *kind* of value:

- consumption: the test cycle. WLTP, the old NEDC (≈20–25% lower) and real-world figures are different
  attributes and are never compared with each other. A manufacturer's WLTP range gives its upper bound.
- service intervals: "16" next to "thousand km" is 16,000 km; "5" next to "years" is 60 months.
- gearbox: an e-CVT, CVT or BEV reduction has no gear count; an ICE gearbox has at least 2 speeds; a
  value of another gearbox or driven axle than the identified variant belongs to another variant (FR-028).
- computed results: a yearly ownership cost outside the configured range is flagged, never scored.

Rules are data (config/sense.yaml), passed in by the caller. Every rejection carries a rule id
"sense.<attribute>.<rule>".
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

Cycle = Literal["WLTP", "NEDC", "REAL", "EPA"]
Gearbox = Literal["manual", "automatic", "dct", "cvt", "e-cvt", "single"]

WLTP_FROM_YEAR = 2018  # cars homologated before September 2018 carry NEDC figures unless the text says WLTP

_REAL = (
    "real", "medido", "en nuestra prueba", "nuestro recorrido", "test average", "on test", "real-world",
    "real world", "we averaged", "averaged", "verbrauch im test", "testverbrauch", "consumo medio en prueba",
)  # fmt: skip
_NEDC = ("nedc", "nefz", "ciclo nedc", "new european driving cycle")
_WLTP = ("wltp",)
_EPA = ("epa",)

_RANGE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:-|–|—|to|a)\s*(\d+(?:[.,]\d+)?)")


RULES: dict[str, Any] = {}


def configure(rules: Mapping[str, Any]) -> None:
    """Install config/sense.yaml (infrastructure calls this at startup and in tests)."""
    RULES.clear()
    RULES.update(rules)


@dataclass(frozen=True)
class SenseResult:
    ok: bool
    value: Any = None
    rule_id: str | None = None
    message: str = ""
    attribute: str | None = None  # set when the value belongs to another attribute (e.g. NEDC consumption)


def _has(text: str, words: tuple[str, ...]) -> bool:
    return any(w in text for w in words)


def consumption_cycle(excerpt: str, generation_from: int | None, source_type: str | None = None) -> Cycle:
    """Test cycle of a consumption figure, from the excerpt; without a marker, from the generation's age."""
    t = excerpt.lower()
    if _has(t, _WLTP):
        return "WLTP"
    if _has(t, _NEDC):
        return "NEDC"
    if _has(t, _REAL):
        return "REAL"
    if _has(t, _EPA) or ("mpg us" in t and "l/100" not in t):
        return "EPA"
    if source_type == "INSTRUMENTED_TEST":
        return "REAL"
    if generation_from is not None and generation_from < WLTP_FROM_YEAR:
        return "NEDC"  # a figure without a cycle for a pre-2018 generation is the NEDC homologation value
    return "WLTP"


CYCLE_ATTRIBUTE: dict[Cycle, str | None] = {
    "WLTP": "consumption",
    "NEDC": "consumption_nedc",
    "REAL": "consumption_real",
    "EPA": None,  # US cycle: not comparable, not stored
}


def classify_consumption(raw_value: str, excerpt: str, generation_from: int | None,
                         source_type: str | None = None) -> SenseResult:  # fmt: skip
    """Which consumption attribute a claim belongs to, and the value to normalise (upper bound of a range)."""
    cycle = consumption_cycle(f"{excerpt} {raw_value}", generation_from, source_type)
    attr = CYCLE_ATTRIBUTE[cycle]
    if attr is None:
        return SenseResult(False, None, "sense.consumption.other_cycle", f"{cycle} figure is not comparable")
    value = raw_value
    m = _RANGE.search(raw_value)
    if m and cycle == "WLTP":
        hi = max(float(m.group(1).replace(",", ".")), float(m.group(2).replace(",", ".")))
        value = f"{hi:g}"  # a WLTP range covers trims and wheels: the upper bound is the conservative figure
    return SenseResult(True, value, None, f"cycle {cycle}", attribute=attr)


def interval_km(v: int | None, rules: Mapping[str, Any] | None = None) -> int | None:
    """Service interval in km: 3–300 read as thousands; anything outside 1,000–300,000 km is not an interval."""
    r = (rules if rules is not None else RULES).get("magnitude", {}).get("service_interval_km", {})
    lo, hi = int(r.get("min", 1000)), int(r.get("max", 300_000))
    t_lo, t_hi = r.get("thousands_if_between", [3, 300])
    if v is None:
        return None
    if v < lo:
        v = v * 1000 if t_lo <= v <= t_hi else 0
    return v if lo <= v <= hi else None


_YEAR_WORDS = ("year", "años", "año", "anos", "jahr", "yr")
_MONTH_WORDS = ("month", "mes", "monat")


def interval_months(v: int | None, excerpt: str = "", rules: Mapping[str, Any] | None = None) -> int | None:
    """Interval in months; "every 5 years" extracted as 5 is converted when the excerpt speaks of years."""
    r = (rules if rules is not None else RULES).get("magnitude", {}).get("service_interval_months", {})
    years = tuple(r.get("year_words", _YEAR_WORDS))
    months = tuple(r.get("month_words", _MONTH_WORDS))
    if v is None:
        return None
    ex = excerpt.lower()
    if v <= int(r.get("years_if_at_most", 15)) and _has(ex, years) and not _has(ex, months):
        v *= 12
    return v if int(r.get("min", 1)) <= v <= int(r.get("max", 240)) else None


def gearbox_family(text: str | None) -> Gearbox | None:
    """Gearbox family of a transmission text (canonical or raw)."""
    if not text:
        return None
    t = " " + text.lower().replace("-", " ") + " "
    if _has(t, ("e cvt", "ecvt", "power split", "planetary", "e:hev", "hybrid synergy")):
        return "e-cvt"
    if _has(t, ("single speed", "single ratio", "reduction", "1 speed direct")):
        return "single"
    if _has(t, (" cvt", "continuously variable", "variador")):
        return "cvt"
    if _has(t, ("dual clutch", "dct", "dsg", "doble embrague", "s tronic", "edc")):
        return "dct"
    # an automatic with a "manual mode" / paddles is still an automatic
    if _has(t, ("auto", "steptronic", "tiptronic", "torque converter", " at ", "geartronic", "sportshift")):
        return "automatic"
    if _has(t, ("manual", "manuell", " mt ")):
        return "manual"
    return None


# Generic "automatic" is what many sources write for an e-CVT, CVT or DCT: compatible with those.
_AUTOMATIC_LIKE = {"automatic", "e-cvt", "cvt", "dct", "single"}


def gearbox_conflict(variant: str | None, claimed: str | None) -> bool:
    """True when a claimed gearbox cannot be the variant's gearbox (manual vs automatic, DCT vs e-CVT)."""
    a, b = gearbox_family(variant) or variant, gearbox_family(claimed)
    if not a or not b or a == b:
        return False
    if "manual" in (a, b):
        return True
    if {a, b} <= {"cvt", "e-cvt"}:
        return False  # sources call a hybrid's e-CVT simply "CVT"
    return "automatic" not in (a, b) and a in _AUTOMATIC_LIKE and b in _AUTOMATIC_LIKE


def drive_conflict(variant: str | None, claimed: str | None) -> bool:
    return bool(variant and claimed and variant.upper() != claimed.upper())


def gear_count(value: float, transmission: str | None, powertrain: str | None,
               rules: Mapping[str, Any] | None = None) -> SenseResult:  # fmt: skip
    """A gear count must be a real stepped gearbox: none for e-CVT/CVT/BEV reductions, ≥ 2 for an ICE."""
    r = (rules if rules is not None else RULES).get("meaning", {}).get("gear_count", {})
    fam = gearbox_family(transmission)
    if fam in tuple(r.get("no_count_for", ("e-cvt", "cvt", "single"))) or (powertrain or "").upper() == "BEV":
        return SenseResult(False, None, "sense.gear_count.no_steps", f"{fam or 'electric'} drive has no gear count")
    if value < int(r.get("min_ice", 2)):
        if (powertrain or "").upper() in ("HEV", "PHEV"):
            return SenseResult(False, None, "sense.gear_count.no_steps", "a one-speed hybrid is an e-CVT")
        return SenseResult(False, None, "sense.gear_count.min", f"{value:g} speed is not a gearbox")
    return SenseResult(True, value)


def tco_per_year(eur: float, age_years: int | None, rules: Mapping[str, Any] | None = None) -> SenseResult:
    """A computed yearly ownership cost outside the class-independent range is an error upstream."""
    r = (rules if rules is not None else RULES).get("results", {}).get("tco_per_year_eur", {})
    lo, hi = float(r.get("min", 800)), float(r.get("max", 15000))
    if (age_years or 0) <= int(r.get("max_age_years", 15)) and not lo <= eur <= hi:
        return SenseResult(False, eur, "sense.tco.out_of_range", f"€{eur:,.0f}/year outside €{lo:,.0f}–€{hi:,.0f}")
    return SenseResult(True, eur)


# --- market of a source --------------------------------------------------------------------------------------

EUROPE = {"es", "pt", "fr", "de", "it", "nl", "be", "at", "ch", "uk", "gb", "ie", "pl", "se", "dk", "no", "fi", "cz",
          "eu", "lu"}  # fmt: skip
_TLD_MARKET = {".com.au": "au", ".co.nz": "nz", ".co.in": "in", ".com.my": "my", ".co.za": "za", ".com.br": "br",
               ".com.mx": "mx", ".co.jp": "jp", ".ca": "ca", ".co.uk": "uk", ".es": "es", ".de": "de", ".fr": "fr",
               ".it": "it", ".pt": "pt"}  # fmt: skip
_PATH_MARKET = re.compile(r"/(?:content/dam/[a-z]+/)?([a-z]{2})(?:[-_/](?:[a-z]{2})?)(?:/|$)")
_COUNTRIES = {"my", "au", "nz", "in", "za", "br", "mx", "jp", "ca", "us", "sg", "th", "id", "ph", "kr", "cn", "tw",
              "ae", "sa", "tr", "ar", "cl", "co"} | EUROPE  # fmt: skip


_US_SITES = ("edmunds.com", "caranddriver.com", "motortrend.com", "consumerreports.org", "iseecars.com",
             "jdpower.com", "kbb.com", "cars.com", "repairpal.com")  # fmt: skip


def market_of(url: str) -> str | None:
    """Country a page is written for, from its domain or a country segment in its path ("/my/en/", "/es-es/")."""
    u = url.lower().split("?")[0]
    host = u.split("//", 1)[-1].split("/", 1)[0]
    if any(host == d or host.endswith("." + d) for d in _US_SITES):
        return "us"
    for tld, m in _TLD_MARKET.items():
        if host.endswith(tld):
            return m
    path = "/" + u.split("//", 1)[-1].split("/", 1)[-1] if "/" in u.split("//", 1)[-1] else "/"
    for seg in re.findall(r"/([a-z]{2})(?=[/_-])", path)[:3]:
        if seg in _COUNTRIES:
            return str(seg)
    return None


def market_fits(url: str, area: str) -> SenseResult:
    """Maintenance schedules and official prices differ by market: only European (prices: Spanish or unknown)
    sources count. A Malaysian 6-month schedule is not the Spanish one (user report 2026-11-02, Tucson)."""
    m = market_of(url)
    if m is None:
        return SenseResult(True)
    if area == "price" and m != "es":
        return SenseResult(False, None, "sense.price.other_market", f"price for market {m.upper()}")
    if area == "maintenance" and m not in EUROPE:
        return SenseResult(False, None, "sense.maintenance.other_market", f"schedule for market {m.upper()}")
    return SenseResult(True)


_SERVICE_ITEMS = ("engine oil", "oil change", "oil and filter", "aceite", "service", "inspection", "revisión",
                  "mantenimiento", "ölwechsel", "inspektion")  # fmt: skip


def service_interval_from_items(items: list[tuple[str, int | None, int | None]]) -> tuple[int | None, int | None]:
    """The main service interval (km, months) from a schedule: the engine-oil / periodic-service item."""
    main = [(k, m) for name, k, m in items if any(w in name.lower() for w in _SERVICE_ITEMS) and (k or m)]
    if not main:
        return None, None
    # the normal schedule, not the "severe conditions" one (shorter intervals) that many tables list too
    kms = [k for k, _ in main if k]
    months = [m for _, m in main if m]
    return (max(kms) if kms else None), (max(months) if months else None)


# --- prices (live chat 2026-11-03: "150 159 4,75%" = 150 CV, 159 g/km, 4.75 % tax was read as €150,159) ----------

_CURRENCY = re.compile(r"€|\beur\b|\beuros?\b", re.I)


def money_marked(raw_value: str, excerpt: str) -> SenseResult:
    """A price is accepted only when its number is written with a currency next to it in the excerpt."""
    digits = re.sub(r"\D", "", raw_value.split(",")[0] if re.search(r",\d{2}$", raw_value) else raw_value)
    if not digits:
        return SenseResult(False, None, "sense.price.no_number", "no number")
    pattern = r"(?<!\d)" + r"[\s., ]?".join(digits) + r"(?![\d])"
    for m in re.finditer(pattern, excerpt):
        around = excerpt[max(0, m.start() - 6) : m.end() + 10]
        if _CURRENCY.search(around):
            return SenseResult(True, raw_value)
    return SenseResult(False, None, "sense.price.no_currency", f"{raw_value} is not written as a price in the excerpt")


def price_outliers(values: list[float], factor: float = 1.6) -> set[int]:
    """Indexes of prices far from the others (> factor × or < 1/factor × the median of all); needs ≥ 3 values."""
    if len(values) < 3:
        return set()
    s = sorted(values)
    med = s[len(s) // 2] if len(s) % 2 else (s[len(s) // 2 - 1] + s[len(s) // 2]) / 2
    return {i for i, v in enumerate(values) if v > med * factor or v < med / factor}
