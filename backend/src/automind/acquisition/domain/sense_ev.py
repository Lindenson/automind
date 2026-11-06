"""Meaning rules for electric values (spec 006 US2, FR-007, FR-008; research R4). Pure.

The words around a value decide what it is, never its size alone:
- a plug-in hybrid's "consumption" is the weighted WLTP figure (useless for costs), the charge-sustaining one
  (empty battery) or the electric kWh/100 km;
- a battery figure is gross or usable;
- kWh is energy, kW is power;
- a DC charging time must be for a 10–80 % (or 20–80 %) window.
Pair checks catch what one value cannot show: a range the battery cannot give, a charging power above the
battery's plausible C-rate, a usable capacity above the gross one.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping

from automind.shared.evidence.sense import SenseResult

PLUG_IN = ("PHEV", "EREV")
FUEL_ATTRS = ("consumption", "consumption_real", "consumption_cs", "consumption_weighted")
EV_ATTRS = ("consumption_ev", "consumption_ev_real", "consumption_ev_plug", "consumption_ev_cltc")
WEIGHTED_MAX = 3.0  # l/100 km: below this a plug-in's headline WLTP figure is the weighted one
MIN_KWH_PER_100KM = 10.0  # the most efficient cars on sale: a range above usable kWh × 10 km is impossible
MAX_C_RATE = 5.0  # DC peak kW ≤ 5 × usable kWh
MIN_USABLE_SHARE = 0.80  # usable is at least 80 % of gross

_WEIGHTED = ("ponderad", "weighted", "gewichtet", "взвешен", "combinado ponderado", "wltp ponderado", "加权")
# Chinese pages (chat 2026-11-06): 亏电油耗 / 馈电油耗 is the consumption with an empty battery
_CS = ("descargad", "sin batería", "sin bateria", "modo híbrido", "modo hibrido", "charge sustaining",
       "charge-sustaining", "empty battery", "battery depleted", "depleted", "flat battery", "leerer akku",
       "leerem akku", "akku leer", "разряжен", "пустой батаре", "batería agotada", "bateria agotada",
       "mínimo de carga", "minimo de carga", "hybrid mode", "cs mode",
       "亏电", "馈电", "电量保持")  # fmt: skip
_GROSS = (
    "bruta",
    "bruto",
    "brute",
    "brută",
    "bruta",
    "lorda",
    "lordo",
    "gross",
    "brutto",
    "total",
    "nominal",
    "полная",
    "брутто",
)
_USABLE = ("útil", "util", "neta", "neto", "usable", "net ", "netto", "nette", "nutzbar", "полезн", "нетто")
_PLUG = ("enchufe", "de la red", "at the wall", "from the wall", "at the plug", "ab steckdose", "inkl. ladeverl",
         "incluidas las pérdidas", "including charging losses", "из розетки")  # fmt: skip
_DC_WINDOW = re.compile(r"\b(10|20)\s*(%|por ciento)?\s*(-|–|—|a|al|to|bis|до)\s*(80)\s*%?")
_SUMMER = ("verano", "summer", "sommer", "лет")
_WINTER = ("invierno", "winter", "frío", "frio", "kälte", "зим", "холод")
_MOTORWAY = ("autopista", "autovía", "autovia", "motorway", "highway", "autobahn", "120 km/h", "130 km/h", "трасс")


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text or "").lower()).strip()


def _has(text: str, words: tuple[str, ...]) -> bool:
    return any(w in text for w in words)


def _is_kwh(unit: str | None, raw: str) -> bool:
    t = f"{unit or ''} {raw}".lower().replace(" ", "")
    return "kwh" in t or "wh/km" in t


def _number(raw: str) -> float | None:
    m = re.search(r"\d+(?:[.,]\d+)?", raw or "")
    return float(m.group(0).replace(",", ".")) if m else None


def plug_in_consumption(attribute: str, raw_value: str, unit: str | None, excerpt: str) -> SenseResult:
    """Which consumption a plug-in hybrid figure is (research R4): weighted, charge-sustaining or electric."""
    text = _norm(f"{excerpt} {raw_value}")
    if _is_kwh(unit, raw_value):
        to = attribute if attribute in EV_ATTRS else ("consumption_ev_real" if attribute == "consumption_real"
                                                      else "consumption_ev")  # fmt: skip
        if to == "consumption_ev_real" and _has(text, _PLUG):
            to = "consumption_ev_plug"
        return SenseResult(True, raw_value, None, "electric consumption", attribute=to)
    if _has(text, _CS):
        return SenseResult(True, raw_value, None, "charge-sustaining (empty battery)", attribute="consumption_cs")
    value = _number(raw_value)
    if _has(text, _WEIGHTED) or (value is not None and value < WEIGHTED_MAX):
        return SenseResult(True, raw_value, "sense.phev.weighted", "weighted WLTP figure: shown, never priced",
                           attribute="consumption_weighted")  # fmt: skip
    if attribute == "consumption_cs" and not _has(text, _WEIGHTED):
        # the reader filed it as "empty battery" from the page (a table under such a header: the excerpt is only the
        # row) and it is too high to be the weighted figure (live run 2026-11-04, autohled.cz "CVT | 5.50 l/100 km")
        return SenseResult(True, raw_value, "sense.phev.cs_by_reader", "charge-sustaining (as read from the page)",
                           attribute="consumption_cs")  # fmt: skip
    return SenseResult(False, None, "sense.phev.unclear_consumption",
                       "a plug-in figure without 'empty battery' or 'weighted' words is not used")  # fmt: skip


# --- test cycle of an electric range or kWh/100 km (chat 2026-11-06, Deepal S09 vs Li L9) ------------------------
# A Chinese page states the CLTC cycle (≈ WLTP × 1.15–1.2, well above real use) unless it says WLTP / WLTC; an NEDC
# range is older and still more optimistic: neither is ever filed or shown as WLTP.
CYCLE_ATTRS = {"range_wltp": ("range_wltp", "range_cltc"), "range_cltc": ("range_wltp", "range_cltc"),
               "consumption_ev": ("consumption_ev", "consumption_ev_cltc"),
               "consumption_ev_cltc": ("consumption_ev", "consumption_ev_cltc")}  # fmt: skip
_CJK = re.compile(r"[\u4e00-\u9fff]")
_CN_HOST = re.compile(r"^(?:[a-z0-9-]+\.)*[a-z0-9-]+\.cn$")


def chinese_source(excerpt: str, url: str = "") -> bool:
    """The excerpt is Chinese or the page is on a Chinese domain."""
    host = url.lower().split("//", 1)[-1].split("/", 1)[0]
    return bool(_CJK.search(excerpt or "")) or bool(host and _CN_HOST.match(host))


def ev_cycle(attribute: str, raw_value: str, excerpt: str, url: str = "") -> SenseResult:
    """WLTP or CLTC for an electric range or kWh/100 km: the words decide ("CLTC", "WLTP", "WLTC"), else a Chinese
    page is CLTC and any other page WLTP. An NEDC range is not comparable and not used."""
    if attribute not in CYCLE_ATTRS:
        return SenseResult(True, raw_value, attribute=attribute)
    wltp, cltc = CYCLE_ATTRS[attribute]
    text = _norm(f"{excerpt} {raw_value}")
    if "cltc" in text:
        return SenseResult(True, raw_value, None, "cycle CLTC (China)", attribute=cltc)
    if "wltp" in text or "wltc" in text:
        return SenseResult(True, raw_value, None, "cycle WLTP", attribute=wltp)
    if "nedc" in text:
        return SenseResult(False, None, "sense.ev.nedc_cycle", "an NEDC electric figure is not comparable")
    if chinese_source(excerpt, url) or attribute == cltc:
        return SenseResult(True, raw_value, None, "cycle CLTC (Chinese source)", attribute=cltc)
    return SenseResult(True, raw_value, None, "cycle WLTP", attribute=wltp)


def battery_kind(raw_value: str, excerpt: str) -> str:
    """battery_gross_kwh when the words say gross; else battery_kwh (usable, or the only figure published)."""
    text = _norm(f"{excerpt} {raw_value}")
    if _has(text, _GROSS) and not _has(text, _USABLE):
        return "battery_gross_kwh"
    return "battery_kwh"


def unit_word_after(raw_value: str, excerpt: str) -> str | None:
    """The unit written right after the value in the excerpt ("60 kWh" → "kwh"), to catch kW/kWh mix-ups."""
    num = re.escape((raw_value or "").strip().split(" ")[0])
    if not num:
        return None
    m = re.search(num + r"\s*(kwh|kw)\b", _norm(excerpt))
    return m.group(1) if m else None


def check_claim(attribute: str, raw_value: str, unit: str | None, excerpt: str) -> SenseResult:
    """Single-value meaning rules: kWh vs kW, the DC time window."""
    after = unit_word_after(raw_value, excerpt)
    if attribute in ("charge_ac_kw", "charge_dc_peak_kw") and (after == "kwh" or _is_kwh(unit, "")):
        return SenseResult(False, None, "sense.ev.energy_for_power", "kWh is energy, not charging power")
    if attribute in ("battery_kwh", "battery_gross_kwh") and (after == "kw" or (unit or "").strip().lower() == "kw"):
        return SenseResult(False, None, "sense.ev.power_for_energy", "kW is power, not battery capacity")
    if attribute == "charge_dc_10_80_min" and not _DC_WINDOW.search(_norm(excerpt)):
        return SenseResult(False, None, "sense.ev.dc_window", "a DC time is compared only for 10–80 %")
    return SenseResult(True, raw_value)


def range_conditions(excerpt: str) -> str:
    """summer | winter | motorway | mixed, from the words of a real-world range test."""
    text = _norm(excerpt)
    for name, words in (("winter", _WINTER), ("motorway", _MOTORWAY), ("summer", _SUMMER)):
        if _has(text, words):
            return name
    return "mixed"


def pair_check(attribute: str, value: float, known: Mapping[str, float]) -> SenseResult:
    """Cross-value rules (FR-007): range vs usable battery, DC power vs C-rate, usable vs gross."""
    usable = known.get("battery_kwh")
    gross = known.get("battery_gross_kwh")
    if attribute in ("range_wltp", "range_real", "range_cltc") and usable and value > usable / MIN_KWH_PER_100KM * 100:
        why = f"{value:g} km needs under {MIN_KWH_PER_100KM:g} kWh/100 km from {usable:g} kWh"
        return SenseResult(False, None, "sense.ev.range_above_battery", why)
    if attribute == "charge_dc_peak_kw" and usable and value > MAX_C_RATE * usable:
        why = f"{value:g} kW is above {MAX_C_RATE:g}C for {usable:g} kWh"
        return SenseResult(False, None, "sense.ev.c_rate", why)
    if attribute == "battery_kwh" and gross and not (MIN_USABLE_SHARE * gross <= value <= gross):
        return SenseResult(False, None, "sense.ev.gross_usable_ratio", f"usable {value:g} vs gross {gross:g} kWh")
    if attribute == "battery_gross_kwh" and usable and not (MIN_USABLE_SHARE * value <= usable <= value):
        return SenseResult(False, None, "sense.ev.gross_usable_ratio", f"gross {value:g} vs usable {usable:g} kWh")
    return SenseResult(True, value)


def split_warranty(text: str) -> dict[str, float]:
    """ "8 años o 160.000 km, 70 %" → years, km and guaranteed capacity, each a separate checked value (US6 AS2)."""
    t = _norm(text)
    out: dict[str, float] = {}
    if m := re.search(r"(\d{1,2})\s*(años|anos|years|year|jahre|лет|года)", t):
        out["years"] = float(m.group(1))
    if m := re.search(r"(\d{1,3}(?:[.,\s]\d{3})+|\d{2,7})\s*(km|kilómetros|kilometres|kilometers|км)", t):
        out["km"] = float(re.sub(r"[.,\s]", "", m.group(1)))
    if m := re.search(r"(\d{2})\s*%", t):
        out["soh_pct"] = float(m.group(1))
    return out


# --- brand presence (spec 006 US6, FR-017; research R12) ----------------------------------------------------
NETWORK_WORDS = ("concesionari", "puntos de venta", "punto de venta", "puntos de servicio", "taller", "dealer",
                 "service point", "service centre", "service center", "workshop", "distribuidor", "red oficial",
                 "дилер", "сервис", "автосалон", "händler", "werkstatt", "concession")  # fmt: skip
NETWORK_RANGE = (1, 2000)
COUNT_WINDOW = 40  # characters between the number and a network word
WARRANTY_YEARS = {"WARRANTY": (2, 10), "BATTERY_WARRANTY": (3, 12)}
WARRANTY_KM = (50_000, 1_000_000)
SOH_RANGE = (60, 80)


def _spans(text: str, number: float) -> list[tuple[int, int]]:
    n = f"{number:g}"
    variants = {n, f"{int(number):,}".replace(",", "."), f"{int(number):,}"} if number == int(number) else {n}
    out = []
    for v in variants:
        out += [(m.start(), m.end()) for m in re.finditer(rf"(?<![\d.,]){re.escape(v)}(?![\d])", text)]
    return out


def count_context(number: float | None, excerpt: str) -> SenseResult:
    """A dealer or workshop count only next to a network word ("BYD cuenta con 120 concesionarios"), never a
    number that belongs to something else ("120 km de autonomía")."""
    rule = "sense.brand.count_context"
    if number is None:
        return SenseResult(True, None, rule)
    if not NETWORK_RANGE[0] <= number <= NETWORK_RANGE[1] or number != int(number):
        return SenseResult(False, None, rule, f"{number:g} is not a plausible network size")
    t = _norm(excerpt)
    for a, b in _spans(t, number):
        around = t[max(0, a - COUNT_WINDOW) : b + COUNT_WINDOW]
        tail = t[b : b + 12]
        if re.match(r"\s*(km|kw|kwh|cv|hp|€|eur|%|años|anos|years|mm|kg|l\b)", tail):
            continue
        if _has(around, NETWORK_WORDS):
            return SenseResult(True, int(number), rule)
    return SenseResult(False, None, rule, f"{number:g} is not next to a dealer or workshop word")


def warranty_check(kind: str, excerpt: str) -> SenseResult:
    """A car or battery warranty: years (and km, % capacity when stated) within the published ranges."""
    rule = "sense.brand.warranty"
    parts = split_warranty(excerpt)
    lo, hi = WARRANTY_YEARS.get(kind, (2, 12))
    if "years" not in parts or not lo <= parts["years"] <= hi:
        return SenseResult(False, None, rule, "no plausible warranty years")
    if "km" in parts and not WARRANTY_KM[0] <= parts["km"] <= WARRANTY_KM[1]:
        parts.pop("km")
    if "soh_pct" in parts and (kind != "BATTERY_WARRANTY" or not SOH_RANGE[0] <= parts["soh_pct"] <= SOH_RANGE[1]):
        parts.pop("soh_pct")
    return SenseResult(True, parts, rule)
