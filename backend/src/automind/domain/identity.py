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

DUPLICATE_THRESHOLD = 92.0


def _norm(s: str | None) -> str:
    return re.sub(r"\s+", " ", (s or "").strip()).lower()


@dataclass(frozen=True)
class Aliases:
    makes: Mapping[str, str] = field(default_factory=dict)  # lower alias -> canonical make
    models: Mapping[str, tuple[str, str]] = field(default_factory=dict)  # "make|alias" -> (make, model)
    generations: Mapping[str, Mapping[str, str]] = field(default_factory=dict)  # "make|model" -> alias -> gen

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
        return cls(makes=makes, models=models, generations=gens)


_EMPTY = Aliases()


def normalize_make_model(make: str, model: str, aliases: Aliases = _EMPTY) -> tuple[str, str]:
    """Canonical (make, model). A model alias may also correct the make ("Land Rover Prado" → Toyota)."""
    mk = aliases.makes.get(_norm(make), make.strip())
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
_FAMILY_RE = re.compile(
    r"(?<![\w-])(" + "|".join(re.escape(f) for f in sorted(_FAMILIES, key=len, reverse=True)) + r")(?![\w-])", re.I
)
_FUEL_WORDS: tuple[tuple[str, str], ...] = (
    (r"plug[- ]?in|\bphev\b|enchufable|подключаем|подзаряж|розетк", "phev"),
    (r"mild[- ]?hybrid|\bmhev\b|мягк\w* гибрид|micro ?h[ií]brid", "mhev"),
    (r"el[eé]ctric|электр|\bbev\b|\bev\b|\b100 ?% ?el", "bev"),
    (r"h[ií]brid|гибрид|\bhev\b", "hybrid"),
    (r"diesel|дизел|gas[oó]leo|солярк", "diesel"),
    (r"gasolina|бензин|petrol|gasoline", "petrol"),
    (r"\bglp\b|\blpg\b|\bгаз\b|autogas", "lpg"),
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
    from .casefile import EngineHint  # local import: casefile does not import identity

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
    family = None
    if m := _FAMILY_RE.search(text):
        family = next(f for f in _FAMILIES if f.lower() == m.group(1).lower())
    fuel = _FAMILIES.get(family) if family else None
    if fuel is None:
        low = text.lower()
        fuel = next((f for pat, f in _FUEL_WORDS if re.search(pat, low)), None)
    if disp is not None and not 0.6 <= disp <= 8.0:
        disp = None
    if not any((disp, hp, kw, family, fuel)):
        return None
    return EngineHint(displacement_l=disp, power_hp=hp, power_kw=kw, fuel=fuel, family=family,  # type: ignore[arg-type]
                      evidence=text.strip()[:120])  # fmt: skip


def engine_fits(hint: Any, engine_cc: int | None, power_kw: int | None, fuel: str | None) -> bool:
    """A variant fits the named engine when every stated field matches (unknown variant fields never exclude)."""
    if hint is None:
        return True
    if hint.displacement_l and engine_cc and abs(engine_cc / 1000 - hint.displacement_l) > 0.05:
        return False
    if hint.power_kw and power_kw and abs(power_kw - hint.power_kw) > 3:
        return False
    return not (hint.fuel and fuel and hint.fuel != fuel)
