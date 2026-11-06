"""The catalogue as identification uses it (over `acquisition.api`, spec 012 T028): the model lines known for a
make, the versions of a model, and a resolved identity stored as a catalogue version with canonical names (one
spelling per make, the model line apart from the version, no make or model repeated in the version name)."""

from __future__ import annotations

from typing import Any

from automind.acquisition import api as acquisition
from automind.acquisition.api import CatalogueVariant, VariantDraft
from automind.chat.application.services.identification.contracts import VariantIdentity
from automind.chat.domain.identification.variant_match import model_line
from automind.shared.contracts.config import Reference
from automind.shared.vehicle import identity

RESEARCH_AREAS = ("specs", "price", "maintenance")  # a car's data is fresh when these areas are


async def known_models(make: str, ref: Reference) -> set[str]:
    """Model lines known for a make: catalog plus config/generations.yaml."""
    models = await acquisition.catalogue_models(make)
    models |= {k.split("|", 1)[1] for k in ref.generations if k.split("|", 1)[0].lower() == make.lower()}
    return models


async def find_variants(make: str, model: str) -> list[CatalogueVariant]:
    return await acquisition.find_variants(make, model)


async def get_variant(variant_id: str) -> CatalogueVariant | None:
    return await acquisition.get_variant(variant_id)


async def stale_areas(variant_id: str) -> list[str]:
    """The research areas of a version that are missing or older than their freshness."""
    return await acquisition.stale_areas(variant_id, RESEARCH_AREAS)


async def upsert_variant(ident: VariantIdentity, ref: Reference) -> CatalogueVariant:
    """The catalogue version of a resolved identity (an existing one is reused, FR-019)."""
    make, model = identity.normalize_make_model(ident.make, ident.model, ref.aliases)
    if getattr(ref, "makes", None) is not None:  # "Škoda" → "Skoda" (config/makes.yaml): one spelling per make
        make = ref.makes.canonical(make) or make
    model, trim = model_line(model, await known_models(make, ref))
    ident = _named_version(ident, model, trim)
    name = _strip_prefix(ident.variant_name, make, model, ident.generation)
    if name and name != ident.variant_name:  # "Mazda CX-5 2.0 …" → "2.0 …" (incident 2026-11-03)
        ident = ident.model_copy(update={"variant_name": name})
    gen = identity.normalize_generation(make, model, ident.generation, ref.aliases)
    sold = ref.gearboxes.get(f"{make}|{model}|{(gen or '').lower()}") or []
    if len(sold) == 1 and ident.transmission != sold[0]:  # the generation is sold with one gearbox only
        ident = ident.model_copy(update={"transmission": sold[0]})
    key = identity.canonical_key(make, model, gen, ident.variant_name, ident.powertrain, ref.aliases)
    draft = VariantDraft(
        canonical_key=key, make=make, model=model, generation=gen, variant_name=ident.variant_name,
        powertrain=ident.powertrain, body_class=ident.body_class, generation_years_from=ident.generation_years_from,
        generation_years_to=ident.generation_years_to, vehicle_class=ident.vehicle_class, segment=ident.segment,
        transmission=ident.transmission, drive=ident.drive, trim=ident.trim, trim_level=ident.trim_level,
        price_eur=ident.price_eur, engine_cc=ident.engine_cc, power_kw=ident.power_kw, fuel=ident.fuel,
    )  # fmt: skip
    return await acquisition.upsert_variant(draft)


def variant_dict(v: Any) -> dict[str, Any]:
    """A catalogue version as the plain row the policy, the card and the case keep."""
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
        "engine_cc": v.engine_cc,
        "power_kw": v.power_kw,
        "body_class": v.body_class,
        "fuel": v.fuel,
    }


def _norm_words(s: str | None) -> str:
    return " ".join((s or "").lower().split())


def _named_version(ident: VariantIdentity, model: str, line: str | None) -> VariantIdentity:
    """The model line ("N" of i30 N) and the version name ("Style") are part of the variant name; the model's
    own name is not a version ("Terramar" of the Cupra Terramar)."""
    if line and line.lower() not in ident.variant_name.lower():
        ident = ident.model_copy(update={"variant_name": f"{line} {ident.variant_name}"})
    if ident.trim and _norm_words(ident.trim) == _norm_words(model):
        ident = ident.model_copy(update={"trim": None})
    if ident.trim and ident.trim.lower() not in ident.variant_name.lower():
        ident = ident.model_copy(update={"variant_name": f"{ident.variant_name} {ident.trim}"})
    return ident


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
