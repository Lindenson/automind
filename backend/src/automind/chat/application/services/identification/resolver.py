"""The resolver with sources (spec 004 R6, spec 005 FR-007, FR-009): a catalogue miss is asked of a web reader
(no tools) with the case context and search results; code checks the answer — a model it cannot place is reported
with the closest known names, a new car is the generation on sale now, a used car's generation was built in its
year, a version needs an engine — and stores it in the catalogue with de-dup. A car not sold in Spain
(`car.market`, chat 2026-11-06) is read where it is sold; outside Europe its version never carries a price (spec 009
FR-009)."""

from __future__ import annotations

from typing import Any

from rapidfuzz import fuzz

from automind.acquisition.api import CatalogueVariant
from automind.chat.application.ports import Ports
from automind.chat.application.services.identification.catalogue import known_models, upsert_variant
from automind.chat.application.services.identification.contracts import (
    GenerationMismatch,
    NotOnSale,
    UnknownModel,
    VariantIdentity,
)
from automind.chat.domain import intake
from automind.chat.domain.case import CaseCar
from automind.chat.domain.identification import identification
from automind.chat.domain.identification.variant_match import current_generation
from automind.shared.contracts.config import Reference
from automind.shared.vehicle import identity, markets


async def resolve_with_llm(
    ports: Ports, car: CaseCar, current_year: int, level: str = "BASE", *, lineup: Any = None, insist: str = ""
) -> tuple[CatalogueVariant, VariantIdentity]:
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
    if not markets.european(car.market) and ident.price_eur is not None:
        ident = ident.model_copy(update={"price_eur": None})  # never a euro price from outside Europe
    if current is not None and (ident.generation or "").lower() != current[0].lower():
        ident = await _on_sale_now(ports, car, user, current)
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


async def _on_sale_now(ports: Ports, car: CaseCar, user: str, current: tuple[str, int]) -> VariantIdentity:
    """A NEW car must be the current generation: asked once more with the generation named, then taken."""
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
    if (again.generation or "").lower() == current[0].lower():
        return again
    return again.model_copy(update={
        "generation": current[0], "generation_years_from": current[1], "generation_years_to": None,
        "note": (again.note + " " if again.note else "") + f"Generation set to {current[0]} (new car).",
    })  # fmt: skip


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
        where = "in Spain" if car.market is None else "on its market"
        context.append(f"equipment level wanted: {level} (BASE = the cheapest version OF THIS MODEL on sale {where})")
    if car.market is not None:  # chat 2026-11-06: a car not sold in Spain
        sold = "in other European countries" if car.market == markets.EUROPE else f"on the {car.market} market"
        context.append(f"market: NOT sold in Spain; sold {sold}: return its version sold there; price_eur only "
                       "when a European list price in euros is written, else null")  # fmt: skip
    return context


async def _resolver_docs(ports: Ports, car: CaseCar, lineup: Any = None) -> list[tuple[str, str, str]]:
    """Search results for the resolver: generations and engines, and (new cars) the Spanish price list of versions.
    A model of the make's line-up (spec 005) brings the line-up page that lists it."""
    if ports.acquisition is None:
        return []
    query = " ".join(x for x in (car.make, car.model, car.constraints.generation_hint) if x) or car.request_text
    listed = (m.source_url for m in getattr(lineup, "models", None) or []
              if car.model and m.model.lower() == car.model.lower() and m.source_url)  # fmt: skip
    url = next(listed, None)
    if car.market is None:
        hints = await ports.acquisition.generation_hints(query, lineup_url=url, user_url=car.constraints.url,
                                                         prices=car.condition != "USED")  # fmt: skip
    else:  # a car not sold in Spain: read where it is sold (no prices from outside Europe)
        hints = await ports.acquisition.generation_hints(
            query, lineup_url=url, user_url=car.constraints.url, market=car.market,
            prices=car.condition != "USED" and markets.european(car.market),
        )  # fmt: skip
    return [(h.url, h.title, h.text) for h in hints]


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
    if ident.known_model and not other_model and intake.same_name(ident.model, model):
        # the resolver knows the very model asked, without a generation: it exists, only not on the Spanish line-up
        # (chat 2026-11-06: "not found «Deepal S09» in Spain; nearest: Deepal S09"); identified on another market
        ident.note = (ident.note + " " if ident.note else "") + "Not on the Spanish line-up."
        return
    pool = known | ({ident.model} if ident.known_model and ident.model else set())
    closest = intake.other_names(model, identification.closest_models(model, pool, fuzz.WRatio))
    checked = [str(src.get("url")) for src in getattr(lineup, "sources", None) or [] if src.get("url")]
    raise UnknownModel(f"{make} {model}", [f"{make} {m}" for m in closest], checked)
