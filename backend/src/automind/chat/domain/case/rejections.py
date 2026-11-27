"""A rejection the person stated, recorded on its car (spec 013 S2, I3): the interpreter's `CarRejection` (part of the
`CaseDelta`), the car's current value at a level, and `record_rejections`, which `delta.apply` runs before any car is
replaced so that "not this" refers to the car as the person saw it."""

from __future__ import annotations

from pydantic import BaseModel, Field

from automind.chat.domain.case.car import CaseCar
from automind.chat.domain.case.casefile import CaseFile
from automind.chat.domain.identification.rejection import Rejection, RejectLevel, same_value


class CarRejection(BaseModel):
    """One "not this" of the latest message about one car (the interpreter proposes it, code checks it)."""

    target_key: str = Field(description="The car key the rejection is about, e.g. 'car#1'")
    level: RejectLevel = Field(
        description="What is rejected: MODEL (the model shown is not the one meant), GENERATION, VERSION (the whole "
        "version shown), ENGINE, GEARBOX or DRIVE"
    )
    value: str | None = Field(
        default=None,
        description="The rejected value exactly as the case file has it now (e.g. 'E-Class'); null = the car's "
        "current value at that level",
    )
    wanted: str | None = Field(default=None, description="What the person wants instead, if they said it ('C-Class')")
    evidence: str = Field(description="The person's words of the LATEST message that reject it, verbatim")


def current_value(car: CaseCar, level: RejectLevel) -> str | None:
    """The car's value at a level now: its model, generation, version label, engine, gearbox or driven wheels."""
    k = car.constraints
    if level is RejectLevel.MODEL:
        return car.model
    if level is RejectLevel.GENERATION:
        return k.generation_hint or (car.ladder.generation if car.ladder else None)
    if level is RejectLevel.VERSION:
        return car.label
    if level is RejectLevel.ENGINE:
        return k.version_hint or (k.engine_hint.text() if k.engine_hint and not k.engine_hint.empty() else None)
    if level is RejectLevel.GEARBOX:
        return k.gearbox_hint
    return k.drive_hint


def record_rejections(case: CaseFile, refs: list[CarRejection], log: list[str]) -> None:
    """Each rejection kept on its car (once), the rejected value taken off the car and its version dropped, so the
    car is identified again without it; the card is to be confirmed again. In place.
    Raises ValueError for a car key the case does not have (as every car change of `apply`)."""
    for ref in refs:
        car = case.car(ref.target_key)
        value = ref.value or current_value(car, ref.level)
        if not value:
            continue  # nothing at that level to reject
        wanted = ref.wanted[:160] if ref.wanted else None
        r = Rejection(level=ref.level, value=value[:160], wanted=wanted, evidence=ref.evidence[:240])
        if any(x.level is r.level and same_value(x.value, r.value) for x in car.identity_rejected):
            continue
        car.identity_rejected.append(r)
        _take_off(car, r)
        case.intake.card_confirmed = False
        log.append(f"{car.key}: not {value}" + (f" — wants {r.wanted}" if r.wanted else ""))


def _take_off(car: CaseCar, r: Rejection) -> None:
    """The rejected value leaves the car: a rejected model becomes the one wanted (or unknown: the make's models are
    offered), a rejected hint is cleared; the version found is dropped (kept as previous_label)."""
    k = car.constraints
    if r.level is RejectLevel.MODEL and same_value(car.model, r.value):
        car.model = r.wanted
        k.generation_hint, k.version_hint, k.trim_hint = None, None, None
    elif r.level is RejectLevel.GENERATION and same_value(k.generation_hint, r.value):
        k.generation_hint = None
    elif r.level in (RejectLevel.VERSION, RejectLevel.ENGINE):
        k.version_hint = None
        if k.engine_hint is not None and same_value(k.engine_hint.text(), r.value):
            k.engine_hint = None  # the engine the person named is the one rejected
    elif r.level is RejectLevel.GEARBOX and same_value(k.gearbox_hint, r.value):
        k.gearbox_hint = None
    elif r.level is RejectLevel.DRIVE and same_value(k.drive_hint, r.value):
        k.drive_hint = None
    if car.label:
        car.previous_label = car.label
    car.variant_id, car.label, car.resolution, car.alternatives = None, None, "UNRESOLVED", []
    car.identify, car.ladder, car.chosen_for_me = None, None, False
