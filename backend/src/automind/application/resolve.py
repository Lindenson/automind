"""Variant resolution: catalog first, context-aware, validated, no duplicates (FR-006..FR-008, FR-024; R6).

1. `assess_car` looks a case car up in the catalog by canonical make/model, generation hint and the
   years implied by its condition/age, and reports a policy `CarState`.
2. If the catalog has no fitting variant, `resolve_with_llm` asks the resolver (a web reader, no
   tools) with the case context; code validates the generation years against the requested year
   and upserts the variant with de-dup.
"""

from __future__ import annotations

import re
from datetime import timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field
from rapidfuzz import fuzz
from sqlalchemy import func, select

from automind.application import research
from automind.application.ports import Ports, Reference
from automind.config import settings
from automind.domain import identification, identity, sense
from automind.domain.casefile import CaseCar
from automind.domain.policy import CarState
from automind.infrastructure import db

CATEGORIES = ("specs", "price", "maintenance")
UNIQUE_MARGIN = 5.0  # a fuzzy winner must beat the runner-up by this many points


class VariantIdentity(BaseModel):
    """Exact vehicle identity proposed by the resolver (a web reader: no tools)."""

    make: str = Field(description="Manufacturer, e.g. 'Toyota'")
    model: str = Field(description="Model, e.g. 'Land Cruiser Prado'")
    generation: str | None = Field(description="Generation code, e.g. 'J150', 'Mk8', 'F30'")
    generation_years_from: int | None = Field(description="First production year of this generation")
    generation_years_to: int | None = Field(description="Last production year of this generation (null if current)")
    variant_name: str = Field(description="Engine/trim, e.g. '3.0 D-4D 173 PS automatic'")
    powertrain: Literal["ICE", "BEV", "HEV", "PHEV", "MHEV"]
    body_class: Literal["HATCHBACK", "SEDAN", "WAGON", "COUPE", "CONVERTIBLE", "SUV", "MPV", "PICKUP"] | None = None
    vehicle_class: Literal["small", "compact", "mid_large", "premium_suv_4x4"] | None = None
    segment: str | None = Field(default=None, description="Market segment, e.g. 'C-SUV', 'D', 'large 4x4'")
    transmission: Literal["manual", "automatic", "dct", "cvt", "e-cvt", "single"] | None = Field(
        default=None, description="Gearbox of this version"
    )
    drive: Literal["FWD", "RWD", "AWD"] | None = Field(default=None, description="Driven wheels of this version")
    trim: str | None = Field(default=None, description="Equipment level name of this version, e.g. 'Klass', 'Homura'")
    trim_level: Literal["BASE", "MID", "TOP"] | None = Field(
        default=None, description="Position of this version in the model's Spanish price list: BASE = cheapest"
    )
    price_eur: int | None = Field(default=None, description="Official Spanish list price of this version (PVP), EUR")
    engine_cc: int | None = Field(default=None, description="Engine displacement in cm³ (e.g. 1498); null for BEV")
    power_kw: int | None = Field(default=None, description="Maximum power in kW")
    fuel: Literal["petrol", "diesel", "hybrid", "mhev", "phev", "bev", "lpg"] | None = Field(
        default=None, description="Fuel / energy of this version"
    )
    known_model: bool = Field(default=True, description="False if no such make/model exists or you are not sure")
    certainty: Literal["exact", "likely", "ambiguous"]
    alternatives: list[str] = Field(default_factory=list, description="Other plausible variants (max 3)")
    note: str = Field(default="", description="Short note, e.g. not sold new in Spain")


class Assessment(BaseModel):
    state: CarState
    candidates: list[dict[str, Any]] = Field(default_factory=list)  # catalog variants that fit
    generations: list[str] = Field(default_factory=list)  # plausible generation codes


def variant_dict(v: db.Variant) -> dict[str, Any]:
    return {
        "id": v.id,
        "label": v.label,
        "make": v.make,
        "model": v.model,
        "generation": v.generation,
        "generation_years_from": v.generation_years_from,
        "generation_years_to": v.generation_years_to,
        "variant_name": v.variant_name,
        "powertrain": v.powertrain,
        "trim": v.trim,
        "trim_level": v.trim_level,
        "price_eur": float(v.price_eur) if v.price_eur is not None else None,
        "transmission": v.transmission,
        "drive": v.drive,
    }


def _known_generations(ref: Reference, make: str, model: str, catalog: list[db.Variant]) -> list[tuple[str, Any, Any]]:
    gens = list(ref.generations.get(f"{make}|{model}", []))
    known = {g for g, _, _ in gens}
    for v in catalog:  # generations learned from the catalog (resolver output)
        if v.generation and v.generation not in known and v.generation_years_from:
            gens.append((v.generation, v.generation_years_from, v.generation_years_to))
            known.add(v.generation)
    return gens


def _years(v: db.Variant, ref: Reference | None) -> tuple[int | None, int | None]:
    """Generation years: config/generations.yaml wins over the catalog row (a row stored while the generation
    was current keeps years_to empty after its successor arrived, e.g. RAV4 XA50 after XA60)."""
    lo, hi = v.generation_years_from or v.model_year_from, v.generation_years_to
    if ref is not None and v.generation:
        make, model = identity.normalize_make_model(v.make, v.model, ref.aliases)
        for g, a, b in ref.generations.get(f"{make}|{model}", []):
            if g.lower() == v.generation.lower():
                return a or lo, b
    return lo, hi


def _fits(
    v: db.Variant, car: CaseCar, gen_hint: str | None, current_year: int, ref: Reference | None = None,
    level: str | None = None,
) -> bool:  # fmt: skip
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


def _years_fit(v: db.Variant, car: CaseCar, gen_hint: str | None, current_year: int, ref: Reference | None) -> bool:
    lo, hi = _years(v, ref)
    if car.year is not None:
        if bought_now(car, current_year) and hi is not None and hi < current_year:
            return False  # a new car bought now is the generation on sale now, even "a new 2025" (incident 2026-11-03)
        return lo is None or identity.generation_matches(car.year, lo, hi, tolerance=1)
    if car.condition in ("NEW", "UNKNOWN") and not gen_hint:
        return hi is None or hi >= current_year  # a new car is the current generation
    return True


def bought_now(car: CaseCar, current_year: int) -> bool:
    """A new car with no year or with this or last year's model year: what the dealer sells now."""
    return car.condition == "NEW" and (car.year is None or car.year >= current_year - 1)


def fits(v: db.Variant, car: CaseCar, current_year: int, ref: Reference | None = None) -> bool:
    """The catalogued variant fits this car (generation on sale for a new car, gearbox, drive, engine)."""
    return _fits(v, car, None, current_year, ref)


async def known_models(make: str, ref: Reference) -> set[str]:
    """Model lines known for a make: catalog plus config/generations.yaml."""
    async with db.sessionmaker()() as s:
        rows = await s.execute(select(db.Variant.model).where(func.lower(db.Variant.make) == make.lower()).distinct())
        models = {str(m) for m in rows.scalars()}
    models |= {k.split("|", 1)[1] for k in ref.generations if k.split("|", 1)[0].lower() == make.lower()}
    return models


def model_line(model: str, known: set[str]) -> tuple[str, str]:
    """Split "Golf GTI" into ("Golf", "GTI") when "Golf" is a known model line (longest match wins)."""
    low = model.lower()
    for m in sorted(known, key=len, reverse=True):
        if low == m.lower():
            return m, ""
        if low.startswith(m.lower() + " "):
            return m, model[len(m) :].strip()
    return model, ""


async def catalog_for(make: str, model: str) -> list[db.Variant]:
    async with db.sessionmaker()() as s:
        rows = await s.execute(
            select(db.Variant).where(
                func.lower(db.Variant.make) == make.lower(), func.lower(db.Variant.model) == model.lower()
            )
        )
        return list(rows.scalars())


_POWERTRAIN_WORDS = {"dmi", "dmp", "phev", "hev", "mhev", "ev", "hybrid", "electric", "electrico", "ehev", "etech"}


def same_model(asked: str | None, got: str | None) -> bool:
    """The resolved model is the model the user named (spec 005: never another model of the make). The variant may
    be more specific ("Seal U" → "Seal U DM-i"); the user's name may carry a powertrain word ("Seal U DM-i")."""
    if not asked or not got:
        return True
    a = re.sub(r"[^a-z0-9]", "", identity.transliterate_ru(asked.lower()))
    g = re.sub(r"[^a-z0-9]", "", identity.transliterate_ru(got.lower()))
    if a == g or g.startswith(a):
        return True
    if a.startswith(g):
        rest = a[len(g) :]
        return rest in _POWERTRAIN_WORDS
    return fuzz.ratio(a, g) >= 90


def engine_of_fits(v: db.Variant, hint: Any) -> bool:
    """The variant's engine (stored, else parsed from its name) fits the engine the user named."""
    cc, kw, fuel = v.engine_cc, v.power_kw, v.fuel
    if cc is None and kw is None:
        e = identity.parse_engine(v.variant_name)
        if e is not None:
            cc = round(e.displacement_l * 1000) if e.displacement_l else None
            kw, fuel = e.power_kw, fuel or e.fuel
    return identity.engine_fits(hint, cc, kw, fuel)


def _rank(car: CaseCar, cands: list[db.Variant], level: str | None = None) -> tuple[list[db.Variant], bool]:
    """Order candidates by fuzzy match of the request text (a variant at the comparison's level first);
    ambiguous unless one clearly wins."""
    if len(cands) <= 1:
        return cands, False
    bonus = {v.id: (UNIQUE_MARGIN * 2 if level and v.trim_level == level else 0.0) for v in cands}
    scored = sorted(((fuzz.token_set_ratio(car.request_text.lower(), v.label.lower()) + bonus[v.id], v)
                     for v in cands), key=lambda x: -x[0])  # fmt: skip
    ambiguous = scored[0][0] - scored[1][0] < UNIQUE_MARGIN
    return [v for _, v in scored], ambiguous


async def assess_car(car: CaseCar, ref: Reference, current_year: int, level: str | None = None) -> Assessment:
    if not (car.make and car.model):
        return Assessment(state=CarState(identity_known=False))
    make, model = identity.normalize_make_model(car.make, car.model, ref.aliases)
    model, _trim = model_line(model, await known_models(make, ref))
    gen_hint = identity.normalize_generation(make, model, car.constraints.generation_hint, ref.aliases)
    catalog = await catalog_for(make, model)
    gens = _known_generations(ref, make, model, catalog)
    plausible = identity.plausible_generations(gens, condition=car.condition, year=car.year, current_year=current_year)
    if car.year is not None and bought_now(car, current_year):
        plausible = [g for g, _, hi in gens if g in plausible and (hi is None or hi >= current_year)] or plausible
    if gen_hint:
        plausible = [g for g in plausible if g.lower() == gen_hint.lower()] or [gen_hint]
    fitting = [v for v in catalog if _fits(v, car, gen_hint, current_year, ref, level)]
    ranked, ambiguous = _rank(car, fitting, level)
    fresh = bool(car.variant_id) and not await stale_categories(car.variant_id or "")
    mixed = bool(car.variant_id) and await gearbox_mixed(car.variant_id or "")
    return Assessment(
        state=CarState(
            identity_known=True,
            in_catalog=bool(ranked),
            ambiguous=ambiguous,
            plausible_generations=len(plausible),
            data_fresh=fresh,
            gearbox_mixed=mixed,
        ),
        candidates=[variant_dict(v) for v in ranked[:4]],
        generations=plausible,
    )


def auto_resolve(car: CaseCar, a: Assessment) -> bool:
    """Unambiguous, catalogued, not used: resolve without asking (FR-006). Returns True if set."""
    if car.resolution in ("CONFIRMED", "AUTO_OK", "PROPOSED") or car.condition == "USED":
        return False  # a proposal waits for the user (spec 005)
    if a.state.in_catalog and not a.state.ambiguous and a.candidates:
        best = a.candidates[0]
        car.variant_id, car.label, car.resolution = best["id"], best["label"], "AUTO_OK"
        return True
    return False


async def resolve_with_llm(
    ports: Ports, car: CaseCar, current_year: int, level: str = "BASE", *, lineup: Any = None, insist: str = ""
) -> tuple[db.Variant, VariantIdentity]:
    """Catalog miss: ask the resolver with the case context, validate years, upsert with de-dup."""
    docs = await _resolver_docs(ports, car, lineup)
    snippets = "\n\n".join(
        f'<untrusted_document url="{u}">\n{t}\n{x[:1500]}\n</untrusted_document>' for u, t, x in docs[:8]
    )
    current = current_generation(ports.ref, car, current_year)
    context = _context(car, current, level)
    named = " ".join(x for x in (car.make, car.model) if x)
    user = (
        f"User's car: {car.display_name} (the user's words: {car.request_text})\n"
        + (f"Model asked: {named} — return a version of exactly this model, never another model of the make.\n"
           if car.make and car.model else "")
        + f"Case context: {'; '.join(context)}\nCurrent year: {current_year}\n{insist}\n"
        f"Search results:\n{snippets or '(none)'}"
    )  # fmt: skip
    ident = await ports.llm.structured("resolver", VariantIdentity, ports.ref.prompts["resolver"], user)
    await _check_known(ports.ref, car, ident, lineup)
    if current is not None and (ident.generation or "").lower() != current[0].lower():
        # a NEW car must be the current generation: ask once more with the generation named, then take it
        again = await ports.llm.structured(
            "resolver", VariantIdentity, ports.ref.prompts["resolver"],
            user + f"\n\nThe car is bought NEW: it is the {current[0]} generation ({current[1]}–). "
            "Return that generation and one of its engines.",
        )  # fmt: skip
        named = car.constraints.engine_hint is not None and not car.constraints.engine_hint.empty()
        if (again.generation or "").lower() != current[0].lower() and named:
            # the engine the user named belongs to another generation: never stamp the current generation on it
            # (incident 2026-11-03: "3rd gen 2.0 165 CV" was a KF engine); the engines on sale are offered instead
            raise NotOnSale(f"{again.make} {again.model} {again.generation or ''} {again.variant_name}".strip())
        ident = again if (again.generation or "").lower() == current[0].lower() else again.model_copy(
            update={"generation": current[0], "generation_years_from": current[1], "generation_years_to": None,
                    "note": (again.note + " " if again.note else "") + f"Generation set to {current[0]} (new car)."}
        )  # fmt: skip
    if (
        car.year
        and ident.generation_years_from
        and not identity.generation_matches(
            car.year, ident.generation_years_from, ident.generation_years_to, tolerance=1
        )
    ):
        raise GenerationMismatch(
            f"{ident.make} {ident.model} {ident.generation} ({ident.generation_years_from}–"
            f"{ident.generation_years_to or 'now'}) does not match ~{car.year}"
        )
    if (
        ident.powertrain != "BEV"
        and not (ident.engine_cc or ident.power_kw)
        and not identity.parse_engine(ident.variant_name)
    ):
        # a version without an engine ("Homura (2025+)") is an equipment level, not a variant: never stored
        raise NotOnSale(f"{ident.make} {ident.model} {ident.variant_name}: no engine named")
    if car.constraints.url and ident.price_eur is not None:
        # a page the user sent is read for this chat only: its price never enters the shared catalogue, where it
        # would reach every other chat (reviewer 2026-11-03); the price then comes from research with sources
        ident = ident.model_copy(update={"price_eur": None})
    return await upsert_variant(ident, ports.ref), ident


def _context(car: CaseCar, current: tuple[str, int] | None, level: str) -> list[str]:
    context = [f"condition: {car.condition}"]
    if car.year:
        context.append(f"year: ~{car.year} (age {car.age_years})")
    hints = car.constraints.model_dump(exclude_none=True)
    if hints:
        context.append("hints: " + ", ".join(f"{k}={v}" for k, v in hints.items()))
    if current is not None:
        context.append(f"current generation (sold new now): {current[0]} ({current[1]}–)")
    if car.constraints.engine_hint is not None and not car.constraints.engine_hint.empty():
        e = car.constraints.engine_hint
        context.append(f"engine named by the user: {e.text()} (return a version with this engine, or say none exists)")
    if car.constraints.trim_hint:
        context.append(f"version named by the user: {car.constraints.trim_hint} (return its trim_level)")
    elif car.condition != "USED":
        context.append(f"equipment level wanted: {level} (BASE = the cheapest version OF THIS MODEL on sale in Spain)")
    return context


async def _resolver_docs(ports: Ports, car: CaseCar, lineup: Any = None) -> list[tuple[str, str, str]]:
    """Search results for the resolver: generations and engines, and (new cars) the Spanish price list of versions.
    A model of the make's line-up (spec 005) brings the line-up page that lists it."""
    query = " ".join(x for x in (car.make, car.model, car.constraints.generation_hint) if x) or car.request_text
    docs: list[tuple[str, str, str]] = []  # (url, title, text)
    store = ports.page_store
    for m in getattr(lineup, "models", None) or []:
        if car.model and m.model.lower() == car.model.lower() and m.source_url:
            page = await store.get(m.source_url, area="price")
            if page:
                docs.append((page.url, page.title, page.text))
            break
    if car.constraints.url:
        page = await store.get(car.constraints.url, area="specs")
        if page:
            docs.append((page.url, page.title, page.text))
    hits = await ports.search.search(f"{query} generation years engines specifications", market="EN", area="specs")
    docs += [(h.url, h.title, h.snippet) for h in hits[:5]]
    # the snippets alone rarely give production years: read the top two pages too (cache-first)
    for h in hits[:2]:
        page = await store.get(h.url, area="specs")
        if page:
            docs.append((page.url, page.title, page.text))
    if car.condition != "USED":  # versions and official prices, for the equal-level comparison (FR-029)
        prices = await ports.search.search(f"{query} precio versiones acabados España", market="ES", area="price")
        docs += [(h.url, h.title, h.snippet) for h in prices[:3]]
    return docs


async def _check_known(ref: Reference, car: CaseCar, ident: VariantIdentity, lineup: Any = None) -> None:
    """Never invent a variant: a model unknown to the catalog, config and the make's line-up that the resolver
    cannot place (no generation, or another model than asked) is reported with the closest known models
    (FR-031; spec 005 FR-007, FR-009: "unknown" only after the line-up lookup)."""
    make, model = identity.normalize_make_model(car.make or ident.make, car.model or ident.model, ref.aliases)
    in_lineup = {m.model for m in getattr(lineup, "models", None) or []}
    known = await known_models(make, ref) | in_lineup
    if any(model.lower() == m.lower() for m in known):
        if in_lineup and not ident.generation and any(model.lower() == m.lower() for m in in_lineup):
            ident.note = (ident.note + " " if ident.note else "") + "Model from the Spanish line-up of the make."
        return
    asked = model.lower().replace("-", "").replace(" ", "")
    got = ident.model.lower().replace("-", "").replace(" ", "")
    other_model = fuzz.ratio(asked, got) < 80
    if ident.known_model and ident.generation and not other_model:
        return  # a model new to us but known to the resolver
    pool = known | ({ident.model} if ident.known_model and ident.model else set())
    closest = identification.closest_models(model, pool, fuzz.WRatio)
    checked = [str(src.get("url")) for src in getattr(lineup, "sources", None) or [] if src.get("url")]
    raise UnknownModel(f"{make} {model}", [f"{make} {m}" for m in closest], checked)


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


class UnknownModel(ValueError):
    """The make/model is not known to the catalog, config or the resolver (spec 004 US8 scenario 2)."""

    def __init__(self, name: str, closest: list[str], checked: list[str] | None = None) -> None:
        super().__init__(f"unknown model {name!r}")
        self.closest = closest
        self.checked = checked or []


class NotOnSale(ValueError):
    """The resolver could not name a version of the generation on sale with an engine (spec 007 F): the user is
    offered the catalogued engines instead of an invented variant."""


class GenerationMismatch(ValueError):
    """The resolver proposed a generation outside the requested years (never accepted silently)."""


async def upsert_variant(ident: VariantIdentity, ref: Reference) -> db.Variant:
    make, model = identity.normalize_make_model(ident.make, ident.model, ref.aliases)
    model, trim = model_line(model, await known_models(make, ref))
    if trim and trim.lower() not in ident.variant_name.lower():
        ident = ident.model_copy(update={"variant_name": f"{trim} {ident.variant_name}"})
    if ident.trim and ident.trim.lower() not in ident.variant_name.lower():  # the version is part of the identity
        ident = ident.model_copy(update={"variant_name": f"{ident.variant_name} {ident.trim}"})
    name = _strip_prefix(ident.variant_name, make, model, ident.generation)
    if name and name != ident.variant_name:  # "Mazda CX-5 2.0 …" → "2.0 …" (incident 2026-11-03)
        ident = ident.model_copy(update={"variant_name": name})
    gen = identity.normalize_generation(make, model, ident.generation, ref.aliases)
    sold = ref.gearboxes.get(f"{make}|{model}|{(gen or '').lower()}") or []
    if len(sold) == 1 and ident.transmission != sold[0]:  # the generation is sold with one gearbox only
        ident = ident.model_copy(update={"transmission": sold[0]})
    key = identity.canonical_key(make, model, gen, ident.variant_name, ident.powertrain, ref.aliases)
    async with db.sessionmaker()() as s:
        found = (await s.execute(select(db.Variant).where(db.Variant.canonical_key == key))).scalar_one_or_none()
        if found is None:
            same = (
                await s.execute(
                    select(db.Variant).where(
                        func.lower(db.Variant.make) == make.lower(), func.lower(db.Variant.model) == model.lower()
                    )
                )
            ).scalars()
            new = {"make": make, "model": model, "generation": gen, "powertrain": ident.powertrain,
                   "variant_name": ident.variant_name}  # fmt: skip
            found = next((v for v in same if identity.is_duplicate(variant_dict(v), new, fuzz.token_sort_ratio)), None)
        if found is not None:
            if found.generation_years_from is None and ident.generation_years_from:
                found.generation_years_from = ident.generation_years_from
                found.generation_years_to = ident.generation_years_to
            for col in ("transmission", "drive", "trim", "trim_level", "price_eur"):
                if getattr(found, col) is None and getattr(ident, col) is not None:
                    setattr(found, col, getattr(ident, col))
            await s.commit()
            return found
        v = db.Variant(
            canonical_key=key,
            make=make,
            model=model,
            generation=gen,
            variant_name=ident.variant_name,
            powertrain=ident.powertrain,
            body_class=ident.body_class,
            model_year_from=ident.generation_years_from,
            generation_years_from=ident.generation_years_from,
            generation_years_to=ident.generation_years_to,
            vehicle_class=ident.vehicle_class,
            segment=ident.segment,
            transmission=ident.transmission,
            drive=ident.drive,
            trim=(ident.trim or None) and ident.trim[:64],
            trim_level=ident.trim_level,
            price_eur=ident.price_eur,
            engine_cc=ident.engine_cc if ident.engine_cc and 600 <= ident.engine_cc <= 8000 else None,
            power_kw=ident.power_kw if ident.power_kw and 30 <= ident.power_kw <= 750 else None,
            fuel=ident.fuel,
        )
        s.add(v)
        await s.commit()
        return v


def _strip_prefix(name: str, make: str, model: str, generation: str | None) -> str:
    """The variant name without the make, model and generation the resolver sometimes repeats in it."""
    out = name.strip()
    for _ in range(3):
        before = out
        for w in (make, model, generation):
            if w and out.lower().startswith(w.lower() + " "):
                out = out[len(w) :].strip()
        if out == before:
            break
    return out or name


async def compare_level(cars: list[CaseCar]) -> tuple[str, str]:
    """The equipment level of the comparison: the level of the first version the user named, else BASE."""
    named = []
    for c in cars:
        if c.constraints.trim_hint and c.variant_id:
            v = await get_variant(c.variant_id)
            named.append(v.trim_level if v is not None else None)
    return identification.level_for(named)  # type: ignore[arg-type]


async def revalidate_level(car: CaseCar, level: str) -> str | None:
    """A car proposed or auto-resolved at another level than the comparison's is identified again; a version
    the user named or confirmed is kept."""
    if not car.variant_id or car.constraints.trim_hint or car.resolution == "CONFIRMED" or car.condition == "USED":
        return None
    v = await get_variant(car.variant_id)
    if v is None or not v.trim_level or v.trim_level == level:
        return None
    old = car.label or v.label
    car.variant_id, car.label, car.resolution = None, None, "UNRESOLVED"
    return f"{car.key}: {old} re-identified at the {level.lower()} level"


async def revalidate(car: CaseCar, ref: Reference, current_year: int) -> str | None:
    """A car resolved earlier by older rules may be the wrong generation now (a new car on a finished
    generation, a catalog row without a generation). Reset it so it is identified again; returns the reason."""
    if not car.variant_id or car.condition == "USED" or (car.year is not None and not bought_now(car, current_year)):
        return None
    v = await get_variant(car.variant_id)
    if v is None or _fits(v, car, None, current_year, ref):
        return None
    old = car.label or v.label
    car.variant_id, car.label, car.resolution = None, None, "UNRESOLVED"
    reason = "no generation recorded" if not v.generation else f"{v.generation} is not the generation sold new now"
    return f"{car.key}: {old} re-identified ({reason})"


async def gearbox_mixed(variant_id: str) -> bool:
    """Accepted values of several gearboxes for one variant without a known gearbox (the CX-5 had manual and
    automatic): the user is asked which one (spec 004 FR-028)."""
    v = await get_variant(variant_id)
    if v is None or v.transmission:
        return False
    return research.mixed_families(await research.accepted_gearboxes(variant_id))


async def split_by_gearbox(car: CaseCar, ref: Reference) -> str | None:
    """The user named the gearbox (or drive) of a mixed variant: identify the variant with that gearbox.
    Returns a change note, or None when nothing changed."""
    k = car.constraints
    if not car.variant_id or not (k.gearbox_hint or k.drive_hint):
        return None
    v = await get_variant(car.variant_id)
    if v is None:
        return None
    gb_ok = not k.gearbox_hint or (v.transmission and not sense.gearbox_conflict(v.transmission, k.gearbox_hint))
    dr_ok = not k.drive_hint or (v.drive and not sense.drive_conflict(v.drive, k.drive_hint))
    if gb_ok and dr_ok:
        return None
    if (v.transmission and k.gearbox_hint and sense.gearbox_conflict(v.transmission, k.gearbox_hint)) or (
        v.drive and k.drive_hint and sense.drive_conflict(v.drive, k.drive_hint)
    ):
        old = car.label or v.label
        car.variant_id, car.label, car.resolution = (
            None,
            None,
            "UNRESOLVED",
        )  # a known other gearbox: find the right one
        return f"{car.key}: {old} is another gearbox or drive; identified again"
    extra = " ".join(x for x in (k.gearbox_hint, k.drive_hint) if x)
    ident = VariantIdentity(
        make=v.make, model=v.model, generation=v.generation, generation_years_from=v.generation_years_from,
        generation_years_to=v.generation_years_to, variant_name=f"{v.variant_name} {extra}",
        powertrain=v.powertrain,  # type: ignore[arg-type]
        body_class=v.body_class, vehicle_class=v.vehicle_class, segment=v.segment,  # type: ignore[arg-type]
        transmission=k.gearbox_hint or v.transmission, drive=k.drive_hint or v.drive,  # type: ignore[arg-type]
        trim=v.trim, trim_level=v.trim_level, price_eur=int(v.price_eur) if v.price_eur else None,  # type: ignore[arg-type]
        certainty="exact",
    )  # fmt: skip
    new = await upsert_variant(ident, ref)
    car.variant_id, car.label, car.resolution = new.id, new.label, "CONFIRMED"
    return f"{car.key}: {new.label} (the gearbox you named)"


async def get_variant(variant_id: str) -> db.Variant | None:
    async with db.sessionmaker()() as s:
        return await s.get(db.Variant, variant_id)


async def stale_categories(variant_id: str) -> list[str]:
    async with db.sessionmaker()() as s:
        runs = {
            r.area: r
            for r in (await s.execute(select(db.ResearchRun).where(db.ResearchRun.variant_id == variant_id))).scalars()
        }
    out = []
    for cat in CATEGORIES:
        r = runs.get(cat)
        if r is None or db.now() - r.completed_at > timedelta(days=settings().freshness_days(cat)):
            out.append(cat)
    return out
