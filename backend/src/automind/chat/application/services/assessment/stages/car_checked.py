"""One car checked against the catalogue before the policy decides: a version set earlier checked again (still
fitting, at the comparison's level, of one gearbox), the car looked up, and auto-resolved when one version clearly
wins."""

from __future__ import annotations

from automind.chat.application.services.identification import assessment, revalidation
from automind.chat.application.services.identification.contracts import Assessment
from automind.chat.domain.case import CaseCar
from automind.shared.contracts.config import Reference


async def car_checked(car: CaseCar, ref: Reference, year: int, level: str) -> tuple[Assessment, list[str]]:
    """The car's assessment and what changed on it (in place): a version dropped or split, the car resolved."""
    changes: list[str] = []
    reason = (
        await revalidation.revalidate(car, ref, year)
        or await revalidation.revalidate_level(car, level)
        or await revalidation.split_by_gearbox(car, ref)
    )
    if reason:
        changes.append(reason)
    a = await assessment.assess_car(car, ref, year, level)
    if assessment.auto_resolve(car, a):
        changes.append(f"{car.key} → {car.label}")
    return a, changes
