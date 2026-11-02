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
