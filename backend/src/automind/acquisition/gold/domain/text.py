"""How gold compares names, fuels and numbers: text normalised for matching, a make through its aliases, the fuel
vocabulary of the datasets, a value within a tolerance and the registration-weighted median."""

from __future__ import annotations

import re
import unicodedata

ICE_FUELS = frozenset({"petrol", "diesel", "lpg", "cng", "e85"})
FUEL_SYNONYMS = {"gasoline": "petrol", "benzine": "petrol", "electric": "bev", "hev": "hybrid", "mhev": "hybrid",
                 "plug-in": "phev"}  # fmt: skip

Tolerance = tuple[str, float]  # ("abs" | "rel", value)

_NOT_ALNUM = re.compile(r"[^a-z0-9]+")


def norm_text(s: str) -> str:
    """Lower case, accents and punctuation stripped, spaces collapsed."""
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return " ".join(_NOT_ALNUM.sub(" ", s).split())


def tokens(name: str, strip_words: tuple[str, ...] = ()) -> tuple[str, ...]:
    """The normalised words of a name without the marketing words."""
    return tuple(t for t in norm_text(name).split() if t not in strip_words)


def canonical_make(make: str, aliases: dict[str, list[str]]) -> str:
    """The make's canonical name (normalised) when it is an alias in config/makes.yaml, else itself normalised."""
    n = norm_text(make)
    for canon, names in aliases.items():
        if n == norm_text(canon) or n in {norm_text(a) for a in names}:
            return norm_text(canon)
    return n


def norm_fuel(fuel: str | None) -> str | None:
    """A fuel in the datasets' vocabulary (`hybrid` covers HEV and MHEV)."""
    if fuel is None:
        return None
    f = fuel.strip().lower()
    return FUEL_SYNONYMS.get(f, f)


def within(value: float, reference: float, tol: Tolerance) -> bool:
    """Whether `value` is within `tol` of `reference` (absolute, or relative to the reference)."""
    kind, t = tol
    return abs(value - reference) <= (t if kind == "abs" else t * abs(reference)) + 1e-9


def weighted_median(pairs: list[tuple[float, int]]) -> float:
    """Median of values weighted by registrations (each weight at least 1; the lower median on a tie)."""
    items = sorted((v, max(1, int(w))) for v, w in pairs)
    half = sum(w for _, w in items) / 2
    acc = 0
    for v, w in items:
        acc += w
        if acc >= half:
            return v
    return items[-1][0]
