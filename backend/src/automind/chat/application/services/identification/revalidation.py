"""A version set earlier checked again against what the person says now: another model than named, another
equipment level than the comparison's, a generation no longer on sale for a new car, another gearbox or drive
than named. A version that no longer fits is dropped (the car is identified again); a gearbox named for a version
without one becomes its own version. Each function returns the change note, or None when nothing changed."""

from __future__ import annotations

from automind.chat.application.services.identification.catalogue import get_variant, upsert_variant
from automind.chat.application.services.identification.contracts import VariantIdentity
from automind.chat.domain.case import CaseCar
from automind.chat.domain.identification import identification
from automind.chat.domain.identification.variant_match import bought_now, fits_case, same_model
from automind.shared.contracts.config import Reference
from automind.shared.evidence import sense


async def drop_wrong_variant(car: CaseCar) -> bool:
    """A stored version of another model than the one named (an earlier wrong resolution) is dropped (spec 005)."""
    if not (car.variant_id and car.model):
        return False
    v = await get_variant(car.variant_id)
    if v is None or same_model(car.model, v.model):
        return False
    car.previous_label = car.label or v.label
    car.variant_id, car.label, car.resolution, car.identify = None, None, "UNRESOLVED", None
    return True


async def compare_level(cars: list[CaseCar]) -> tuple[str, str]:
    """The equipment level of the comparison: the level of the first version the user named, else BASE."""
    named = []
    for c in cars:
        if c.constraints.trim_hint and c.variant_id:
            v = await get_variant(c.variant_id)
            named.append(v.trim_level if v is not None else None)
    return identification.level_for(named)


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
    if v is None or fits_case(v, car, None, current_year, ref):
        return None
    old = car.label or v.label
    car.variant_id, car.label, car.resolution = None, None, "UNRESOLVED"
    reason = "no generation recorded" if not v.generation else f"{v.generation} is not the generation sold new now"
    return f"{car.key}: {old} re-identified ({reason})"


async def split_by_gearbox(car: CaseCar, ref: Reference) -> str | None:
    """The user named the gearbox (or drive) of a mixed variant: identify the variant with that gearbox."""
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
        old = car.label or v.label  # a known other gearbox: find the right one
        car.variant_id, car.label, car.resolution = None, None, "UNRESOLVED"
        return f"{car.key}: {old} is another gearbox or drive; identified again"
    extra = " ".join(x for x in (k.gearbox_hint, k.drive_hint) if x)
    ident = VariantIdentity.model_validate({  # catalogue strings, validated as the identity's closed sets
        "make": v.make, "model": v.model, "generation": v.generation, "generation_years_from": v.generation_years_from,
        "generation_years_to": v.generation_years_to, "variant_name": f"{v.variant_name} {extra}",
        "powertrain": v.powertrain, "body_class": v.body_class, "vehicle_class": v.vehicle_class, "segment": v.segment,
        "transmission": k.gearbox_hint or v.transmission, "drive": k.drive_hint or v.drive, "trim": v.trim,
        "trim_level": v.trim_level, "price_eur": int(v.price_eur) if v.price_eur else None, "certainty": "exact",
    })  # fmt: skip
    new = await upsert_variant(ident, ref)
    car.variant_id, car.label, car.resolution = new.id, new.label, "CONFIRMED"
    return f"{car.key}: {new.label} (the gearbox you named)"
