"""A car looked up in the catalogue for the policy (FR-006..FR-008, FR-024; R6): by canonical make and model, the
generation named and the years its condition implies; the fitting versions ranked, whether one clearly wins, and
whether the chosen version's data is fresh and of one gearbox."""

from __future__ import annotations

from automind.acquisition import api as acquisition
from automind.chat.application.services.identification.catalogue import (
    find_variants,
    get_variant,
    known_models,
    stale_areas,
    variant_dict,
)
from automind.chat.application.services.identification.contracts import Assessment
from automind.chat.domain.case import CaseCar
from automind.chat.domain.decision import CarState
from automind.chat.domain.identification.variant_match import (
    bought_now,
    fits_case,
    known_generations,
    model_line,
    rank,
)
from automind.shared.contracts.config import Reference
from automind.shared.vehicle import identity


async def assess_car(car: CaseCar, ref: Reference, current_year: int, level: str | None = None) -> Assessment:
    if not (car.make and car.model):
        return Assessment(state=CarState(identity_known=False))
    make, model = identity.normalize_make_model(car.make, car.model, ref.aliases)
    model, _trim = model_line(model, await known_models(make, ref))
    gen_hint = identity.normalize_generation(make, model, car.constraints.generation_hint, ref.aliases)
    catalog = await find_variants(make, model)
    gens = known_generations(ref, make, model, catalog)
    plausible = identity.plausible_generations(gens, condition=car.condition, year=car.year, current_year=current_year)
    if car.year is not None and bought_now(car, current_year):
        plausible = [g for g, _, hi in gens if g in plausible and (hi is None or hi >= current_year)] or plausible
    if gen_hint:
        plausible = [g for g in plausible if g.lower() == gen_hint.lower()] or [gen_hint]
    fitting = [v for v in catalog if fits_case(v, car, gen_hint, current_year, ref, level)]
    ranked, ambiguous = rank(car, fitting, level)
    fresh = bool(car.variant_id) and not await stale_areas(car.variant_id or "")
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
        candidates=[variant_dict(v) for v in ranked[:8]],
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


async def gearbox_mixed(variant_id: str) -> bool:
    """Accepted values of several gearboxes for one variant without a known gearbox (the CX-5 had manual and
    automatic): the user is asked which one (spec 004 FR-028)."""
    v = await get_variant(variant_id)
    if v is None or v.transmission:
        return False
    return await acquisition.gearbox_families_mixed(variant_id)
