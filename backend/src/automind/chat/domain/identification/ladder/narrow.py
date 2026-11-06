"""Narrowing the versions a model was sold in by what the person said: fuel, engine family, gearbox, power, years on
sale."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import replace
from typing import Any

from automind.chat.domain.identification.ladder.model import (
    AUTO_GEARBOXES,
    GEARBOX_LABEL,
    IMPLIED_FUEL,
    Narrowed,
    Version,
    Wanted,
    cv_label,
    family_word,
    line_of,
)
from automind.shared.text.patterns import whole_word
from automind.shared.vehicle.identity import generation_matches

_DIESEL_WORD = re.compile(r"di[eé]sel|\bd\b|\bdci\b")  # "2.0 diésel", "320d", "1.5 dCi"


def _base_fuel(v: Version) -> str | None:
    """The liquid fuel of a mild hybrid from its engine family ("1.5 TSI m-HEV" → petrol, "2.0 TDI MHEV" → diesel)."""
    low = v.engine.lower()
    hit = next((f for f in IMPLIED_FUEL if whole_word(f, hyphen_inside=True).search(low)), None)
    if hit and IMPLIED_FUEL[hit] in ("petrol", "diesel"):
        return IMPLIED_FUEL[hit]
    return "diesel" if _DIESEL_WORD.search(low) else None


def _fuel_ok(want: str, have: str | None, v: Version | None = None) -> bool:
    if have is None or want == have:
        return True
    if have == "mhev":  # a mild hybrid is still a petrol or a diesel: which one, from its engine family
        base = _base_fuel(v) if v is not None else None
        return want == "hybrid" or (want in ("petrol", "diesel") and base in (want, None))
    return False


def _family_ok(family: str, v: Version) -> bool:
    fam, low = family.lower(), v.engine.lower()
    if whole_word(fam, hyphen_inside=True).search(low):  # "TSI" is not "eTSI"
        return True
    # a family word the source does not write ("TDI" for "2.0 diésel 150 CV"): the fuel decides, unless the
    # source names another family
    implied = IMPLIED_FUEL.get(fam)
    named = any(whole_word(f, hyphen_inside=True).search(low) for f in IMPLIED_FUEL)
    return implied is not None and not named and v.fuel is not None and _fuel_ok(implied, v.fuel, v)


def _gearbox_ok(v: Version, wanted: str) -> bool:
    if not v.gearboxes:
        return True
    if wanted == "automatic":
        return any(g in AUTO_GEARBOXES for g in v.gearboxes)
    return wanted in v.gearboxes


def _replaces(new: Version, old: Version) -> bool:
    """`new` is the facelift of `old`: the same engine (fuel, family, ±0.3 l) first sold in a later year, while
    the source gives `old` no end year."""
    if old.years_to is not None or old.years_from is None or new.years_from is None:
        return False
    if new.years_from <= old.years_from or (new.fuel or "") != (old.fuel or ""):
        return False
    if _family_key(new) != _family_key(old):
        return False
    return new.engine_cc is None or old.engine_cc is None or abs(new.engine_cc - old.engine_cc) <= 300


_FUEL_WORDS = {"phev", "hev", "mhev", "hybrid", "híbrido", "hibrido", "plug-in", "diesel", "diésel", "gasolina",
               "petrol", "ev", "bev", "electric", "eléctrico"}  # fmt: skip


def _family_key(v: Version) -> str:
    """The engine family without fuel words: "T-GDi PHEV" and "T-GDi" are one family (catalog rows write it either
    way)."""
    words = [w for w in (family_word(v) or "").lower().split() if w not in _FUEL_WORDS]
    return words[0] if words else ""


def stale(v: Version, year: int, years: int) -> bool:
    """A version (an unsourced catalog row) a new car bought in `year` may no longer be: first sold `years` or more
    years before, so a facelift may have replaced it without a newer row to say so."""
    return v.years_from is not None and year - v.years_from >= years


def sold_until(v: Version, versions: Sequence[Version]) -> int | None:
    """The last year the version was sold: its own end year, else the year before a facelift replaced it (None:
    still on sale)."""
    if v.years_to is not None:
        return v.years_to
    later = [n.years_from for n in versions if n.years_from is not None and _replaces(n, v)]
    return min(later) - 1 if later else None


def sold_in(v: Version, versions: Sequence[Version], year: int, tolerance: int = 1) -> bool:
    """Was the version sold in `year`? A version without years is sold in every year of its generation."""
    return v.years_from is None or generation_matches(year, v.years_from, sold_until(v, versions), tolerance)


def on_sale(versions: Sequence[Version], year: int) -> list[Version]:
    """The versions a new car bought in `year` can be: the latest of the generation (a version that ended, or that
    a facelift replaced, is not on sale). All of them when the list says nothing about it."""
    now = [v for v in versions if (end := sold_until(v, versions)) is None or end >= year]
    return now or list(versions)


def narrow(versions: Sequence[Version], w: Wanted) -> Narrowed:
    """Filter from the top level down; a statement that no version has is reported and skipped."""
    pool = [v for v in versions if w.year is None or sold_in(v, versions, w.year)] or list(versions)
    named = line_of(w.words)
    lined = [v for v in pool if (line_of(v.engine) or None) == named] if named else []
    if named and lined:
        pool = lined
    elif not named:  # "Octavia" is not the Octavia RS: the line is offered only when named
        pool = [v for v in pool if line_of(v.engine) is None] or pool
    missing: list[str] = []
    if w.engine:
        exact = [v for v in pool if v.engine.lower() == w.engine.lower()]
        if exact:
            pool = exact
    checks: list[tuple[str | None, Any]] = [
        (w.fuel, lambda v: _fuel_ok(w.fuel or "", v.fuel, v)),
        (f"{w.displacement_l:.1f}" if w.displacement_l else None,
         lambda v: v.engine_cc is None or abs(v.engine_cc / 1000 - (w.displacement_l or 0)) <= 0.05),
        (w.family, lambda v: _family_ok(w.family or "", v)),
        (cv_label(w.power_kw) if w.power_kw else None,
         lambda v: v.power_kw is None or abs(v.power_kw - (w.power_kw or 0)) <= 3),
        (GEARBOX_LABEL.get(w.gearbox or "", w.gearbox), lambda v: _gearbox_ok(v, w.gearbox or "")),
        (w.drive, lambda v: not v.drives or w.drive in v.drives),
    ]  # fmt: skip
    for said, ok in checks:
        if not said:
            continue
        fit = [v for v in pool if ok(v)]
        if fit:
            pool = fit
        else:
            missing.append(said)
    return Narrowed(pool, missing)


def without(w: Wanted, missing: Sequence[str]) -> Wanted:
    """The statements that exist: what `narrow` reported missing is not shown as a settled level (FR-013)."""
    gone = set(missing)
    if not gone:
        return w
    return replace(
        w,
        fuel=None if w.fuel in gone else w.fuel,
        displacement_l=None if w.displacement_l and f"{w.displacement_l:.1f}" in gone else w.displacement_l,
        family=None if w.family in gone else w.family,
        power_kw=None if w.power_kw and cv_label(w.power_kw) in gone else w.power_kw,
        gearbox=None if w.gearbox and GEARBOX_LABEL.get(w.gearbox, w.gearbox) in gone else w.gearbox,
        drive=None if w.drive in gone else w.drive,
    )
