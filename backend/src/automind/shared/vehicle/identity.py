"""Exact vehicle identity: alias normalization, canonical keys, generation years, de-dup (R6).

Constitution II: data from different generations or variants is never merged. Aliases come from
config/aliases.yaml (loaded by infrastructure). The fuzzy scorer is injected so the domain stays
dependency-free.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from automind.shared.vehicle.engine import EngineHint

DUPLICATE_THRESHOLD = 92.0


def _norm(s: str | None) -> str:
    return re.sub(r"\s+", " ", (s or "").strip()).lower()


@dataclass(frozen=True)
class Aliases:
    makes: Mapping[str, str] = field(default_factory=dict)  # lower alias -> canonical make
    models: Mapping[str, tuple[str, str]] = field(default_factory=dict)  # "make|alias" -> (make, model)
    generations: Mapping[str, Mapping[str, str]] = field(default_factory=dict)  # "make|model" -> alias -> gen
    # "Make|Model[|Generation]" -> market -> the model's name on that market (spec 009 FR-021)
    market_names: Mapping[str, Mapping[str, str]] = field(default_factory=dict)
    # "Make|Model" -> market -> the whole name in that market's script ("深蓝S09"): home-market searches and the
    # relevance of its pages (chat 2026-11-06)
    local_names: Mapping[str, Mapping[str, str]] = field(default_factory=dict)

    def names_of(self, make: str, model: str) -> list[str]:
        """Every other written name of a model: its aliases ("理想l9", "lixiang l9") and local names, lower case."""
        out = [alias for key, (mk, md) in self.models.items() if (mk, md) == (make, model)
               for alias in [key.partition("|")[2]]]  # fmt: skip
        out += [_norm(n) for n in (self.local_names.get(f"{make}|{model}") or {}).values()]
        return list(dict.fromkeys(n for n in out if n))

    @classmethod
    def from_config(cls, d: Mapping[str, Any]) -> Aliases:
        makes = {_norm(k): str(v) for k, v in (d.get("makes") or {}).items()}
        models: dict[str, tuple[str, str]] = {}
        for k, v in (d.get("models") or {}).items():
            make, _, alias = str(k).partition("|")
            target = (str(v["make"]), str(v["model"])) if isinstance(v, Mapping) else (make, str(v))
            models[f"{_norm(make)}|{_norm(alias)}"] = target
        gens = {
            _norm(k): {_norm(str(a)): str(g) for a, g in (v or {}).items()}
            for k, v in (d.get("generations") or {}).items()
        }
        names = {str(k): {str(m).upper(): str(n) for m, n in (v or {}).items()}
                 for k, v in (d.get("market_names") or {}).items()}  # fmt: skip
        local = {str(k): {str(m).upper(): str(n) for m, n in (v or {}).items()}
                 for k, v in (d.get("local_names") or {}).items()}  # fmt: skip
        return cls(makes=makes, models=models, generations=gens, market_names=names, local_names=local)


_EMPTY = Aliases()


def normalize_make_model(make: str, model: str, aliases: Aliases = _EMPTY) -> tuple[str, str]:
    """Canonical (make, model). A model alias may also correct the make ("Land Rover Prado" → Toyota)."""
    mk = aliases.makes.get(_norm(make), make.strip())
    model = model.strip()
    if (hit := aliases.models.get(f"{_norm(mk)}|{_norm(model)}")) is not None:
        return hit
    for name in {make.strip(), mk}:  # "Mazda CX-5" as the model of Mazda is "CX-5" (incident 2026-11-03)
        if name and model.lower().startswith(name.lower() + " ") and len(model) > len(name) + 1:
            model = model[len(name) + 1 :].strip()
    hit = aliases.models.get(f"{_norm(mk)}|{_norm(model)}")
    if hit is not None:
        return hit
    return mk, re.sub(r"\s+", " ", model.strip())


def normalize_generation(make: str, model: str, generation: str | None, aliases: Aliases = _EMPTY) -> str | None:
    if generation is None or not generation.strip():
        return None
    mk, md = normalize_make_model(make, model, aliases)
    table = aliases.generations.get(f"{_norm(mk)}|{_norm(md)}", {})
    return table.get(_norm(generation), generation.strip())


def canonical_key(
    make: str,
    model: str,
    generation: str | None,
    variant_name: str,
    powertrain: str,
    aliases: Aliases = _EMPTY,
) -> str:
    mk, md = normalize_make_model(make, model, aliases)
    gen = normalize_generation(mk, md, generation, aliases)
    return "|".join([_norm(mk), _norm(md), _norm(gen) or "-", _norm(variant_name), _norm(powertrain)])


def generation_matches(year: int | None, start: int | None, end: int | None, tolerance: int = 0) -> bool:
    """True if `year` (± tolerance) falls within the generation's production years (end None = current)."""
    if year is None or start is None:
        return False
    lo, hi = year - tolerance, year + tolerance
    return hi >= start and (end is None or lo <= end)


def plausible_generations(
    generations: Iterable[tuple[str, int | None, int | None]],
    *,
    condition: str,
    year: int | None,
    current_year: int,
    tolerance: int = 1,
) -> list[str]:
    """Generations that could be meant: by year if given; new car → the current one; used → all sold."""
    gens = list(generations)
    if year is not None:
        return [g for g, lo, hi in gens if generation_matches(year, lo, hi, tolerance)]
    if condition == "NEW":
        return [g for g, lo, hi in gens if hi is None or hi >= current_year]
    return [g for g, lo, hi in gens if lo is not None and lo <= current_year]


def is_duplicate(a: Mapping[str, Any], b: Mapping[str, Any], scorer: Callable[[str, str], float]) -> bool:
    """Same make, model, generation and powertrain, and variant names that score ≥ 92 (FR-024)."""
    for k in ("make", "model", "generation", "powertrain"):
        if _norm(a.get(k)) != _norm(b.get(k)):
            return False
    return scorer(_norm(a.get("variant_name")), _norm(b.get("variant_name"))) >= DUPLICATE_THRESHOLD


def same_version(a: Mapping[str, Any], b: Mapping[str, Any], *, trim_unknown_ok: bool = True) -> bool:
    """The same car under two names ("320d M Sport" and "320d M Sport 8-speed automatic"): same make, model and
    powertrain, the same engine (cm³ within 20, kW within 2, both known), and no field that tells them apart
    (generation, gearbox, driven wheels, body, version name, fuel: equal or unknown on one side). A new car is
    matched with trim_unknown_ok=False: "1.5 TSI Style" is not folded into a row without a version name."""
    for k in ("make", "model", "powertrain"):
        if _norm(a.get(k)) != _norm(b.get(k)):
            return False
    cc_a, cc_b, kw_a, kw_b = a.get("engine_cc"), b.get("engine_cc"), a.get("power_kw"), b.get("power_kw")
    if None in (kw_a, kw_b) or abs(int(kw_a) - int(kw_b)) > 2:  # type: ignore[arg-type]
        return False
    if (cc_a is None) != (cc_b is None) or (cc_a is not None and abs(int(cc_a) - int(cc_b)) > 20):  # type: ignore[arg-type]
        return False
    if not trim_unknown_ok and _norm(a.get("trim")) != _norm(b.get("trim")):
        return False
    for k in ("generation", "transmission", "drive", "body_class", "trim", "fuel"):
        x, y = _norm(a.get(k)), _norm(b.get(k))
        if x and y and x != y:
            return False
    return True


def duplicate_groups(rows: list[Mapping[str, Any]]) -> list[list[str]]:
    """Ids of catalog rows that are one car, groups of 2+ only. Every pair in a group is the same version: a row
    without the driven wheels never joins an RWD and an AWD row into one."""
    groups: list[list[Mapping[str, Any]]] = []
    for r in rows:
        home = next((g for g in groups if all(same_version(r, x) for x in g)), None)
        if home is None:
            groups.append([r])
        else:
            home.append(r)
    return [[str(x["id"]) for x in g] for g in groups if len(g) > 1]


# --- spec 005: engine identity and names in other scripts (research R3, R4) -----------------------------------

_RU = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюя", ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "y", "k", "l",
           "m", "n", "o", "p", "r", "s", "t", "u", "f", "kh", "ts", "ch", "sh", "sch", "", "y", "", "e", "yu", "ya"],
           strict=True))  # fmt: skip


def transliterate_ru(text: str) -> str:
    """Cyrillic → Latin (GOST-like, lower case for Cyrillic letters); other characters unchanged."""
    return "".join(_RU.get(ch, _RU.get(ch.lower(), ch)) if ch.lower() in _RU else ch for ch in text)


def sound_key(text: str) -> str:
    """Consonant skeleton for matching transliterated names ("спортейдж" ≈ "Sportage", "атека" ≈ "Ateca")."""
    s = transliterate_ru(text.lower())
    for a, b in (("dzh", "g"), ("zh", "g"), ("kh", "h"), ("ph", "f"), ("ck", "k"), ("c", "k"), ("q", "k"),
                 ("x", "ks"), ("w", "v"), ("j", "g"), ("ts", "s")):  # fmt: skip
        s = s.replace(a, b)
    s = re.sub(r"[aeiouy\W_]+", "", s)
    return re.sub(r"(.)\1+", r"\1", s)


_FAMILIES: dict[str, str | None] = {  # canonical family -> fuel it implies
    "eTSI": "mhev", "TSI": "petrol", "TFSI": "petrol", "TDI": "diesel", "TGI": None, "DM-i": "phev", "DM-p": "phev",
    "e:HEV": "hybrid", "e-HEV": "hybrid", "EcoBoost": "petrol", "BlueHDi": "diesel", "HDi": "diesel",
    "PureTech": "petrol", "dCi": "diesel", "TCe": "petrol", "D-4D": "diesel", "CRDi": "diesel", "T-GDi": "petrol",
    "GDi": "petrol", "Skyactiv-G": "petrol", "Skyactiv-D": "diesel", "Skyactiv-X": "petrol", "e-Power": "hybrid",
    "E-Tech": "hybrid", "MHEV": "mhev", "PHEV": "phev", "HEV": "hybrid",
}  # fmt: skip
_FAMILY_ALT = "|".join(re.escape(f) for f in sorted(_FAMILIES, key=len, reverse=True))
_FAMILY_RE = re.compile(r"(?<![\w-])(" + _FAMILY_ALT + r")(?![\w-])", re.I)
_FUEL_WORDS: tuple[tuple[str, str], ...] = (  # first match wins: plug-in and mild before plain hybrid, hybrid
    # before electric ("híbrido eléctrico", "hybrid electric" are HEV); VW "e-Hybrid" is a plug-in
    (r"plug[- ]?in|\bphev\b|enchufable|(?<![\w-])e-?hybrid\b|подключаем|подзаряж|розетк", "phev"),
    (r"mild[- ]?hybrid|\bmhev\b|мягк\w* гибрид|micro[- ]?h[iíy]brid|(?<![\d.,])48 ?v\b", "mhev"),
    (r"h[iíy]brid|гибрид|\bhev\b", "hybrid"),
    (r"el[eé]ctric|электр|\bbev\b|\bev\b|\b100 ?% ?el", "bev"),
    (r"diesel|дизел|gas[oó]leo|солярк", "diesel"),
    (r"gasolina|бензин|petrol|gasoline", "petrol"),
    (r"\bglp\b|\blpg\b|\bгаз\b|autogas", "lpg"),
)
_ELECTRIFIED = ("phev", "hybrid", "mhev", "bev")
_GENERIC_FAMILIES = {"MHEV", "PHEV", "HEV"}
# "Corolla hybrid 140", "1.5 TSI 150": a bare number right after the engine word is its power (PS) when nothing
# else follows it (not "140 000 km", "140 €", "140H")
_BARE_HP = re.compile(
    r"(?<!\w)(?:" + _FAMILY_ALT + r"|h[iíy]brid[oa]?|гибрид)"
    r"\s+(\d{2,3})(?![.,]?\d)(?!\s*\d)(?!\s*[^\W\d_])(?!\s*[€$£%])",
    re.I,
)
_NEG_BEFORE = re.compile(r"(?:\bне|\bnot|\bno|\bни|написал\w*|wrote|escribiste|pusiste|было|был)\s*$", re.I)
_DISP = re.compile(r"(?<![\d.,])([0-8])[.,](\d)(?!\d)(?!\s*(?:тыс|k\b|mil|000|км|km))", re.I)
_CC = re.compile(r"(?<!\d)(\d{3,4})\s*(?:cc|cm3|см3|куб)", re.I)
_HP = re.compile(r"(?<!\d)(\d{2,4})\s*(?:cv|ps|hp|bhp|л\.?\s?с\.?|лс|caballos|сил)(?!\w)", re.I)
_KW = re.compile(r"(?<!\d)(\d{2,3})\s*(?:kw|квт)(?!\w)", re.I)


def _last_positive(text: str, pattern: re.Pattern[str]) -> re.Match[str] | None:
    """The last match not negated ("not 1.0", "а не 1.0", "you wrote 1.0"); None if every match is negated."""
    found = [m for m in pattern.finditer(text) if not _NEG_BEFORE.search(text[max(0, m.start() - 14) : m.start()])]
    return found[-1] if found else None


def parse_engine(text: str | None) -> Any:
    """Engine facts in the user's words → `EngineHint`, or None when the text names no engine (R4)."""
    if not text:
        return None
    disp: float | None = None
    if m := _last_positive(text, _DISP):
        disp = float(f"{m.group(1)}.{m.group(2)}")
    elif (m := _last_positive(text, _CC)) and 600 <= int(m.group(1)) <= 8000:
        disp = round(int(m.group(1)) / 1000, 1)
    hp = int(m.group(1)) if (m := _last_positive(text, _HP)) and 40 <= int(m.group(1)) <= 1000 else None
    kw = int(m.group(1)) if (m := _last_positive(text, _KW)) and 30 <= int(m.group(1)) <= 750 else None
    if kw is None and hp is not None:
        kw = round(hp * 0.7355)
    found = [next(f for f in _FAMILIES if f.lower() == m.group(1).lower()) for m in _FAMILY_RE.finditer(text)]
    family = next((f for f in found if f not in _GENERIC_FAMILIES), found[0] if found else None)
    fam_fuels = [_FAMILIES[f] for f in found if _FAMILIES[f]]
    fam_fuel = next((f for f in _ELECTRIFIED if f in fam_fuels), fam_fuels[0] if fam_fuels else None)
    low = text.lower()
    word_fuel = next((f for pat, f in _FUEL_WORDS if re.search(pat, low)), None)
    # a plug-in family (DM-i) is decisive and petrol/diesel words never override a family; otherwise an
    # electrified word does: "T-GDi 48V" → mhev, "T-GDi PHEV" → phev, "E-Tech electric" → bev
    keep_family = fam_fuel == "phev" or word_fuel not in _ELECTRIFIED
    fuel = (fam_fuel or word_fuel) if keep_family else word_fuel
    if hp is None and kw is None and (m := _BARE_HP.search(text)) and 60 <= int(m.group(1)) <= 500:
        hp = int(m.group(1))
        kw = round(hp * 0.7355)
    if disp is not None and not 0.6 <= disp <= 8.0:
        disp = None
    if not any((disp, hp, kw, family, fuel)):
        return None
    return EngineHint(displacement_l=disp, power_hp=hp, power_kw=kw, fuel=fuel, family=family,  # type: ignore[arg-type]
                      evidence=text.strip()[:120])  # fmt: skip


# diesel names without the word "diesel": BMW 320d / xDrive20d, Mercedes C 220 d, Mazda Skyactiv-D, …
_DIESEL_NAME = re.compile(
    r"(?i)(?<![\w.])(?:[sx]drive)?\d{2,3}\s?d(?![\w])|skyactiv[- ]?d\b|\b(?:tdci|jtd|multijet|cdi|bluetec|i-dtec|cdti|"
    r"tdv\d|crdi|dci|d-4d|tdi|hdi|bluehdi|ecoblue|d4|d5)\b|di[eé]sel|дизел"
)


def liquid_fuel(text: str | None) -> str | None:
    """petrol or diesel for the fuel cost of a car whose catalog fuel is a hybrid kind (a 320d mild hybrid burns
    diesel; live chat 48c8ac65 priced it at the petrol price). None when the name does not say."""
    e = parse_engine(text)
    if e is not None and e.fuel in ("petrol", "diesel"):
        return str(e.fuel)
    return "diesel" if text and _DIESEL_NAME.search(text) else None


def engine_fits(hint: Any, engine_cc: int | None, power_kw: int | None, fuel: str | None) -> bool:
    """A variant fits the named engine when every stated field matches (unknown variant fields never exclude)."""
    if hint is None:
        return True
    if hint.displacement_l and engine_cc and abs(engine_cc / 1000 - hint.displacement_l) > 0.05:
        return False
    if hint.power_kw and power_kw and abs(power_kw - hint.power_kw) > 3:
        return False
    if "mhev" in (hint.fuel, fuel):  # a mild hybrid is still a petrol or a diesel ("320d … Mild-Hybrid 190 CV")
        return True
    return not (hint.fuel and fuel and hint.fuel != fuel)
