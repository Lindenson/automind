"""The identification service (spec 005 R1, R2, R10; spec 008; spec 012 S7): every intake turn, each unsettled or
changed car is identified again from its current facts.

Outcome per car (`IdentifyOutcome`):
- IDENTIFIED: nothing to ask about the identity (a version is set, or the catalogue has candidates to confirm);
- CHOICES: concrete options to pick from (models of the make, versions, engines);
- NEED: one named item is missing (MAKE, MODEL, ENGINE, YEAR …);
- NOT_FOUND: looked up and not found; `checked` names what was looked at, `choices` the closest real names.
Never raises UnknownModel to the caller; the policy asks with concrete options instead (FR-009).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from automind.chat.application.ports import Ports
from automind.chat.application.services.identification.contracts import (
    Fallback,
    IdentifyRequest,
    LineupLookup,
    Placed,
)
from automind.chat.application.services.identification.revalidation import drop_wrong_variant
from automind.chat.application.services.identification.stages.ask_model import ask_model
from automind.chat.application.services.identification.stages.catalogue_lookup import catalogue_lookup
from automind.chat.application.services.identification.stages.normalise_name import canonical_make, classify_url
from automind.chat.application.services.identification.stages.place_market import place_on_market, say_where_sold
from automind.chat.application.services.identification.stages.settle import has_version, needs_identify, settle
from automind.chat.application.services.identification.stages.year_first import year_first
from automind.chat.application.services.identification.strategies.catalogue_rows import CatalogueRows
from automind.chat.application.services.identification.strategies.open_world import OpenWorld
from automind.chat.application.services.identification.strategies.sourced_versions import SourcedVersions
from automind.chat.domain.case import CaseCar, CaseFile, IdentifyOutcome

Progress = Callable[[CaseCar], Awaitable[None]]  # called before a car is identified (the chat shows it)


@dataclass
class CarIdentified:
    car: CaseCar
    outcome: IdentifyOutcome
    page_url: str | None  # the page the person sent, as it was before identification read or refused it


@dataclass
class CaseIdentified:
    """`before`: each car's outcome before this turn; `changes`: the case's change log lines."""

    before: dict[str, str | None]
    identified: list[CarIdentified] = field(default_factory=list)
    changes: list[str] = field(default_factory=list)


class IdentificationService:
    """Identifies the cars of a case through named stages and ordered fallback strategies."""

    def __init__(self, ports: Ports, lineup: LineupLookup | None = None) -> None:
        self.ports, self.lineup = ports, lineup
        # sourced versions first, then the catalogue's rows, then the resolver with sources (spec 008 FR-020)
        self.fallbacks: tuple[Fallback, ...] = (SourcedVersions(ports), CatalogueRows(ports), OpenWorld(ports))

    async def run(self, req: IdentifyRequest) -> IdentifyOutcome:
        """Identify one car in place (make and model canonical, a version proposed when found)."""
        ports, case, car = self.ports, req.case, req.car
        note = classify_url(car, ports.ref.makes)
        canonical_make(car, ports.ref.makes)
        if not car.make:
            return settle(car, IdentifyOutcome(outcome="NEED", need="MAKE", note=note))
        names = await catalogue_lookup(ports, car, self.lineup)
        if not car.model:
            return settle(car, ask_model(car, case, names, note))
        if has_version(car):
            return settle(car, IdentifyOutcome(outcome="IDENTIFIED"))
        lineup = await place_on_market(ports, car, self.lineup, names)
        if (year_asked := year_first(ports, case, car, req.current_year)) is not None:
            return year_asked
        found = await self._first_answer(Placed(case, car, req.current_year, lineup))
        return say_where_sold(car, found)

    async def identify_case(
        self, case: CaseFile, current_year: int, progress: Progress | None = None
    ) -> CaseIdentified:
        """Every car whose facts changed since it was identified, identified again; a stored version of another
        model than the one named is dropped first (spec 005)."""
        done = CaseIdentified(before={x.key: (x.identify.outcome if x.identify else None) for x in case.cars})
        for car in case.cars:
            if await drop_wrong_variant(car):
                done.changes.append(f"{car.key}: {car.previous_label} is not a {car.model} — identified again")
            if not needs_identify(car):
                continue
            if progress is not None:
                await progress(car)
            url = car.constraints.url
            o = await self.run(IdentifyRequest(case, car, current_year))
            done.identified.append(CarIdentified(car, o, url))
            if o.outcome != done.before.get(car.key) or car.label:
                done.changes.append(f"{car.key}: {o.outcome.lower()}" + (f" → {car.label}" if car.label else ""))
        return done

    async def _first_answer(self, placed: Placed) -> IdentifyOutcome:
        for fallback in self.fallbacks:
            if (o := await fallback.identify(placed)) is not None:
                return o
        raise AssertionError("the open world always answers")  # pragma: no cover
