"""Does a catalogued version fit the car the person means? Pure matching over catalogue rows (spec 004 FR-028,
FR-029; spec 005 FR-012; incident 2026-11-03): the generation on sale for a new car, the generation built in a used
car's year, the gearbox, driven wheels, engine and equipment level named; the same model under another spelling;
the order of several fitting rows. String similarity is rapidfuzz's (a pure library)."""

from __future__ import annotations

import re
from typing import Any, Protocol, TypeVar

from rapidfuzz import fuzz

from automind.chat.domain.case import CaseCar
from automind.shared.contracts.config import Reference
from automind.shared.evidence import sense
from automind.shared.vehicle import identity


class VariantFacts(Protocol):
    """What matching reads of a catalogue row (`acquisition.api.CatalogueVariant`)."""

    id: str
    make: str
    model: str
    generation: str | None
    variant_name: str
    model_year_from: int | None
    generation_years_from: int | None
    generation_years_to: int | None
    transmission: str | None
    drive: str | None
    trim_level: str | None
    engine_cc: int | None
    power_kw: int | None
    fuel: str | None

    @property
    def label(self) -> str: ...


V = TypeVar("V", bound=VariantFacts)
Span = tuple[str, Any, Any]  # (generation, first year, last year or None)

UNIQUE_MARGIN = 5.0  # a fuzzy winner must beat the runner-up by this many points
POWERTRAIN_WORDS = frozenset({"dmi", "dmp", "phev", "hev", "mhev", "ev", "hybrid", "electric", "electrico", "ehev",
                              "etech"})  # a powertrain word after a model name ("Seal U DM-i")  # fmt: skip
_NOT_ALNUM = re.compile(r"[^a-z0-9]")  # "seal u dm-i" -> "sealudmi"


def bought_now(car: CaseCar, current_year: int) -> bool:
    """A new car with no year or with this or last year's model year: what the dealer sells now."""
    return car.condition == "NEW" and (car.year is None or car.year >= current_year - 1)


def fits(v: VariantFacts, car: CaseCar, current_year: int, ref: Reference | None = None) -> bool:
    """The catalogued variant fits this car (generation on sale for a new car, gearbox, drive, engine)."""
    return fits_case(v, car, None, current_year, ref)


def fits_case(v: VariantFacts, car: CaseCar, gen_hint: str | None, current_year: int, ref: Reference | None = None,
              level: str | None = None) -> bool:  # fmt: skip
    """`fits` with the generation the person named and the comparison's equipment level."""
    if gen_hint and (v.generation or "").lower() != gen_hint.lower():
        return False
    if level and not car.constraints.trim_hint and car.condition != "USED" and v.trim_level and v.trim_level != level:
        return False  # another equipment level than the comparison's (spec 004 FR-029)
    k = car.constraints
    if k.gearbox_hint and v.transmission and sense.gearbox_conflict(v.transmission, k.gearbox_hint):
        return False  # another gearbox than the user's (FR-028)
    if k.drive_hint and v.drive and sense.drive_conflict(v.drive, k.drive_hint):
        return False
    if k.engine_hint is not None and not k.engine_hint.empty() and not engine_of_fits(v, k.engine_hint):
        return False  # another engine than the user's (spec 005 FR-012)
    if ref is not None and not v.generation:  # a catalog row without a generation is not reused when config knows them
        make, model = identity.normalize_make_model(v.make, v.model, ref.aliases)
        if ref.generations.get(f"{make}|{model}"):
            return False
    return _years_fit(v, car, gen_hint, current_year, ref)


def same_model(asked: str | None, got: str | None) -> bool:
    """The resolved model is the model the user named (spec 005: never another model of the make). The variant may
    be more specific ("Seal U" → "Seal U DM-i"); the user's name may carry a powertrain word ("Seal U DM-i")."""
    if not asked or not got:
        return True
    a = _NOT_ALNUM.sub("", identity.transliterate_ru(asked.lower()))
    g = _NOT_ALNUM.sub("", identity.transliterate_ru(got.lower()))
    if a == g or g.startswith(a):
        return True
    if a.startswith(g):
        rest = a[len(g) :]
        return rest in POWERTRAIN_WORDS
    return fuzz.ratio(a, g) >= 90


def engine_of_fits(v: VariantFacts, hint: Any) -> bool:
    """The variant's engine (stored, else parsed from its name) fits the engine the user named."""
    cc, kw, fuel = v.engine_cc, v.power_kw, v.fuel
    if cc is None and kw is None:
        e = identity.parse_engine(v.variant_name)
        if e is not None:
            cc = round(e.displacement_l * 1000) if e.displacement_l else None
            kw, fuel = e.power_kw, fuel or e.fuel
    return identity.engine_fits(hint, cc, kw, fuel)


def rank(car: CaseCar, cands: list[V], level: str | None = None) -> tuple[list[V], bool]:
    """Order candidates by fuzzy match of the request text (a variant at the comparison's level first);
    ambiguous unless one clearly wins."""
    if len(cands) <= 1:
        return cands, False
    bonus = {v.id: (UNIQUE_MARGIN * 2 if level and v.trim_level == level else 0.0) for v in cands}
    # equal scores in a fixed order (the least power first, then the label), never the database's row order
    scored = sorted(((fuzz.token_set_ratio(car.request_text.lower(), v.label.lower()) + bonus[v.id], v)
                     for v in cands), key=lambda x: (-x[0], x[1].power_kw or 10**6, x[1].label))  # fmt: skip
    ambiguous = scored[0][0] - scored[1][0] < UNIQUE_MARGIN
    return [v for _, v in scored], ambiguous


def model_line(model: str, known: set[str]) -> tuple[str, str]:
    """Split "Golf GTI" into ("Golf", "GTI") when "Golf" is a known model line (longest match wins)."""
    low = model.lower()
    for m in sorted(known, key=len, reverse=True):
        if low == m.lower():
            return m, ""
        if low.startswith(m.lower() + " "):
            return m, model[len(m) :].strip()
    return model, ""


def known_generations(ref: Reference, make: str, model: str, catalog: list[V]) -> list[Span]:
    """The model's generations: config/generations.yaml, then those the catalogue learned (resolver output)."""
    gens: list[Span] = list(ref.generations.get(f"{make}|{model}", []))
    known = {g for g, _, _ in gens}
    for v in catalog:
        if v.generation and v.generation not in known and v.generation_years_from:
            gens.append((v.generation, v.generation_years_from, v.generation_years_to))
            known.add(v.generation)
    return gens


def current_generation(ref: Reference, car: CaseCar, current_year: int) -> tuple[str, int] | None:
    """For a NEW car without a year: the generation on sale now according to config/generations.yaml."""
    if car.condition == "USED" or not (car.make and car.model):
        return None
    if car.year is not None and not bought_now(car, current_year):
        return None
    make, model = identity.normalize_make_model(car.make, car.model, ref.aliases)
    gens = [(g, a, b) for g, a, b in ref.generations.get(f"{make}|{model}", []) if a is not None]
    on_sale = [(g, a) for g, a, b in gens if a <= current_year and (b is None or b >= current_year)]
    return max(on_sale, key=lambda x: x[1]) if on_sale else None


def _generation_years(v: VariantFacts, ref: Reference | None) -> tuple[int | None, int | None]:
    """Generation years: config/generations.yaml wins over the catalog row (a row stored while the generation
    was current keeps years_to empty after its successor arrived, e.g. RAV4 XA50 after XA60)."""
    lo, hi = v.generation_years_from or v.model_year_from, v.generation_years_to
    if ref is not None and v.generation:
        make, model = identity.normalize_make_model(v.make, v.model, ref.aliases)
        for g, a, b in ref.generations.get(f"{make}|{model}", []):
            if g.lower() == v.generation.lower():
                return a or lo, b
    return lo, hi


def _years_fit(v: VariantFacts, car: CaseCar, gen_hint: str | None, current_year: int, ref: Reference | None) -> bool:
    lo, hi = _generation_years(v, ref)
    if car.year is not None:
        if bought_now(car, current_year) and hi is not None and hi < current_year:
            return False  # a new car bought now is the generation on sale now, even "a new 2025" (incident 2026-11-03)
        return lo is None or identity.generation_matches(car.year, lo, hi, tolerance=1)
    if car.condition in ("NEW", "UNKNOWN") and not gen_hint:
        return hi is None or hi >= current_year  # a new car is the current generation
    return True
