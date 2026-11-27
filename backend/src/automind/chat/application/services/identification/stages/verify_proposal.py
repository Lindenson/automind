"""Stage verify_proposal (spec 013 S2, T023; I2): a version a strategy just found is checked against what the person
said before it is proposed. A contradiction is never proposed: the version is dropped and the person is asked, the
contradiction named ("you wrote C-Class, I found only the E-Class")."""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Protocol

from automind.acquisition.api import CatalogueVariant
from automind.chat.application.services.identification.rejected import without_rejected_choices
from automind.chat.application.services.identification.stages.settle import has_version, settle
from automind.chat.domain.case import CaseCar, Choice, IdentifyOutcome, IntakeItem
from automind.chat.domain.identification.verify import Contradiction, Fact, verify

NEED_OF: dict[Fact, IntakeItem] = {Fact.MAKE: "MODEL", Fact.MODEL: "MODEL", Fact.GENERATION: "YEAR",
                                   Fact.YEAR: "YEAR", Fact.ENGINE: "ENGINE"}  # fmt: skip
CONTRADICTION_EVENT = "contradiction"  # the notice naming it (dialog phrases)


class VariantById(Protocol):
    """A catalogue version by id (`catalogue.get_variant`), None when it is gone."""

    def __call__(self, variant_id: str, /) -> Awaitable[CatalogueVariant | None]: ...


async def verify_proposal(car: CaseCar, found: IdentifyOutcome, variant_by_id: VariantById) -> IdentifyOutcome:
    """`found` unchanged when no version was set, the version is gone, or nothing the person said contradicts it;
    otherwise the person is asked (CHOICES naming the contradiction) and the car keeps no version. An engine the
    ladder already said does not exist (`found.missing`, the "ladder_missing" notice) is not asked twice."""
    if not (has_version(car) and car.variant_id):
        return found
    row = await variant_by_id(car.variant_id)
    if row is None:
        return found
    c = verify(row, car).contradiction
    if c is None or (c.fact is Fact.ENGINE and found.missing):
        return found
    car.resolution, car.variant_id, car.label = "UNRESOLVED", None, None
    event = {"kind": CONTRADICTION_EVENT, "fact": c.fact.lower(), "said": c.person_said, "found": c.candidate_has}
    return settle(car, IdentifyOutcome(outcome="CHOICES", need=NEED_OF[c.fact], choices=_options(car, c, row),
                                       checked=found.checked, note=found.note,
                                       events=[*found.events, event]))  # fmt: skip


def _options(car: CaseCar, c: Contradiction, row: CatalogueVariant) -> list[Choice]:
    """The person's own words first when the model is contradicted; the version found, to confirm it on purpose
    (never one the person rejected)."""
    make = car.make or row.make
    own = [Choice(label=f"{make} {car.model}", make=make, model=car.model, suggested=True, reason="your_words")]
    found = Choice(label=row.label, make=row.make, model=row.model, variant_id=row.id, reason="contradicted")
    mine = own if c.fact in (Fact.MAKE, Fact.MODEL) and car.model else []
    return [*mine, *without_rejected_choices(car, [found])]
