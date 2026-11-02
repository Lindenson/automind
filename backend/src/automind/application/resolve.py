"""Variant resolution: catalog first, context-aware, validated, no duplicates (FR-006..FR-008, FR-024; R6).

1. `assess_car` looks a case car up in the catalog by canonical make/model, generation hint and the
   years implied by its condition/age, and reports a policy `CarState`.
2. If the catalog has no fitting variant, `resolve_with_llm` asks the resolver (a web reader, no
   tools) with the case context; code validates the generation years against the requested year
   and upserts the variant with de-dup.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field
from rapidfuzz import fuzz
from sqlalchemy import func, select

from automind.application.ports import Ports, Reference
from automind.config import settings
from automind.domain import identity
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


def _fits(v: db.Variant, car: CaseCar, gen_hint: str | None, current_year: int, ref: Reference | None = None) -> bool:
    if gen_hint and (v.generation or "").lower() != gen_hint.lower():
        return False
    if ref is not None and not v.generation:  # a catalog row without a generation is not reused when config knows them
        make, model = identity.normalize_make_model(v.make, v.model, ref.aliases)
        if ref.generations.get(f"{make}|{model}"):
            return False
    lo, hi = _years(v, ref)
    if car.year is not None:
        return lo is None or identity.generation_matches(car.year, lo, hi, tolerance=1)
    if car.condition in ("NEW", "UNKNOWN") and not gen_hint:
        return hi is None or hi >= current_year  # a new car is the current generation
    return True


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


def _rank(car: CaseCar, cands: list[db.Variant]) -> tuple[list[db.Variant], bool]:
    """Order candidates by fuzzy match of the request text; ambiguous unless one clearly wins."""
    if len(cands) <= 1:
        return cands, False
    scored = sorted(((fuzz.token_set_ratio(car.request_text.lower(), v.label.lower()), v) for v in cands),
                    key=lambda x: -x[0])  # fmt: skip
    ambiguous = scored[0][0] - scored[1][0] < UNIQUE_MARGIN
    return [v for _, v in scored], ambiguous


async def assess_car(car: CaseCar, ref: Reference, current_year: int) -> Assessment:
    if not (car.make and car.model):
        return Assessment(state=CarState(identity_known=False))
    make, model = identity.normalize_make_model(car.make, car.model, ref.aliases)
    model, _trim = model_line(model, await known_models(make, ref))
    gen_hint = identity.normalize_generation(make, model, car.constraints.generation_hint, ref.aliases)
    catalog = await catalog_for(make, model)
    gens = _known_generations(ref, make, model, catalog)
    plausible = identity.plausible_generations(gens, condition=car.condition, year=car.year, current_year=current_year)
    if gen_hint:
        plausible = [g for g in plausible if g.lower() == gen_hint.lower()] or [gen_hint]
    fitting = [v for v in catalog if _fits(v, car, gen_hint, current_year, ref)]
    ranked, ambiguous = _rank(car, fitting)
    fresh = bool(car.variant_id) and not await stale_categories(car.variant_id or "")
    return Assessment(
        state=CarState(
            identity_known=True,
            in_catalog=bool(ranked),
            ambiguous=ambiguous,
            plausible_generations=len(plausible),
            data_fresh=fresh,
        ),
        candidates=[variant_dict(v) for v in ranked[:4]],
        generations=plausible,
    )


def auto_resolve(car: CaseCar, a: Assessment) -> bool:
    """Unambiguous, catalogued, not used: resolve without asking (FR-006). Returns True if set."""
    if car.resolution in ("CONFIRMED", "AUTO_OK") or car.condition == "USED":
        return False
    if a.state.in_catalog and not a.state.ambiguous and a.candidates:
        best = a.candidates[0]
        car.variant_id, car.label, car.resolution = best["id"], best["label"], "AUTO_OK"
        return True
    return False


async def resolve_with_llm(ports: Ports, car: CaseCar, current_year: int) -> tuple[db.Variant, VariantIdentity]:
    """Catalog miss: ask the resolver with the case context, validate years, upsert with de-dup."""
    context = [f"condition: {car.condition}"]
    if car.year:
        context.append(f"year: ~{car.year} (age {car.age_years})")
    hints = car.constraints.model_dump(exclude_none=True)
    if hints:
        context.append("hints: " + ", ".join(f"{k}={v}" for k, v in hints.items()))
    query = " ".join(x for x in (car.make, car.model, car.constraints.generation_hint) if x) or car.request_text
    docs: list[tuple[str, str, str]] = []  # (url, title, text)
    store = ports.page_store
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
    snippets = "\n\n".join(
        f'<untrusted_document url="{u}">\n{t}\n{x[:1500]}\n</untrusted_document>' for u, t, x in docs[:7]
    )
    current = current_generation(ports.ref, car, current_year)
    if current is not None:
        context.append(f"current generation (sold new now): {current[0]} ({current[1]}–)")
    user = (
        f"User's car: {car.request_text}\nCase context: {'; '.join(context)}\nCurrent year: {current_year}\n\n"
        f"Search results:\n{snippets or '(none)'}"
    )
    ident = await ports.llm.structured("resolver", VariantIdentity, ports.ref.prompts["resolver"], user)
    if current is not None and (ident.generation or "").lower() != current[0].lower():
        # a NEW car must be the current generation: ask once more with the generation named, then take it
        again = await ports.llm.structured(
            "resolver", VariantIdentity, ports.ref.prompts["resolver"],
            user + f"\n\nThe car is bought NEW: it is the {current[0]} generation ({current[1]}–). "
            "Return that generation and one of its engines.",
        )  # fmt: skip
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
    return await upsert_variant(ident, ports.ref), ident


def current_generation(ref: Reference, car: CaseCar, current_year: int) -> tuple[str, int] | None:
    """For a NEW car without a year: the generation on sale now according to config/generations.yaml."""
    if car.year is not None or car.condition == "USED" or not (car.make and car.model):
        return None
    make, model = identity.normalize_make_model(car.make, car.model, ref.aliases)
    gens = [(g, a, b) for g, a, b in ref.generations.get(f"{make}|{model}", []) if a is not None]
    on_sale = [(g, a) for g, a, b in gens if a <= current_year and (b is None or b >= current_year)]
    return max(on_sale, key=lambda x: x[1]) if on_sale else None


class GenerationMismatch(ValueError):
    """The resolver proposed a generation outside the requested years (never accepted silently)."""


async def upsert_variant(ident: VariantIdentity, ref: Reference) -> db.Variant:
    make, model = identity.normalize_make_model(ident.make, ident.model, ref.aliases)
    model, trim = model_line(model, await known_models(make, ref))
    if trim and trim.lower() not in ident.variant_name.lower():
        ident = ident.model_copy(update={"variant_name": f"{trim} {ident.variant_name}"})
    gen = identity.normalize_generation(make, model, ident.generation, ref.aliases)
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
        )
        s.add(v)
        await s.commit()
        return v


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
