"""Strategy open_world (spec 005 FR-007, FR-009, FR-015): neither sources nor the catalogue identify the car — the
resolver with sources does, less certain. It answers for the model asked or not at all: another model is asked for
once more, then never accepted (the closest real names are offered); a generation not built in the year, a version
not on sale or an engine that does not exist offer the engines there are. The last strategy: it always answers."""

from __future__ import annotations

from automind.chat.application.ports import Ports
from automind.chat.application.services.identification.contracts import (
    GenerationMismatch,
    NotOnSale,
    Placed,
    UnknownModel,
)
from automind.chat.application.services.identification.resolver import resolve_with_llm
from automind.chat.application.services.identification.stages.offer_engines import close_lineup, engines_on_sale
from automind.chat.application.services.identification.stages.place_market import lineup_models
from automind.chat.application.services.identification.stages.settle import proposed, settle
from automind.chat.domain import intake
from automind.chat.domain.case import Choice, IdentifyOutcome
from automind.chat.domain.identification.variant_match import engine_of_fits, same_model

MAX_NAMES = 6  # the line-up's models offered for an unknown one


class OpenWorld:
    def __init__(self, ports: Ports) -> None:
        self.ports = ports

    async def identify(self, placed: Placed) -> IdentifyOutcome:
        o = await self._resolve(placed)
        if o.outcome == "IDENTIFIED":
            o.events.append({"kind": "identity_less_certain"})
        return o

    async def _resolve(self, placed: Placed) -> IdentifyOutcome:  # noqa: PLR0911 - one return per way out
        ports, case, car, year, lineup = self.ports, placed.case, placed.car, placed.year, placed.lineup
        try:
            v, ident = await resolve_with_llm(ports, car, year, case.compare_level, lineup=lineup)
            if not same_model(car.model, v.model):  # the resolver answered another model: insist once
                v, ident = await resolve_with_llm(
                    ports, car, year, case.compare_level, lineup=lineup,
                    insist=f"Your previous answer was {v.model}, which is NOT the model asked ({car.model}). "
                    "Return a version of the model asked, or known_model=false.",
                )  # fmt: skip
            if not same_model(car.model, v.model):  # still another model: never accepted, ask with real options
                car.resolution, car.variant_id, car.label = "UNRESOLVED", None, None
                return settle(car, IdentifyOutcome(outcome="NOT_FOUND", need="MODEL", choices=close_lineup(lineup, car),
                                                   note=f"resolver returned {v.model}"))  # fmt: skip
        except GenerationMismatch as e:
            # the year is known and the version named is of another generation: the versions of that year are
            # offered (asking the year again loops, chat 9b5c0b0c)
            choices = await engines_on_sale(ports, car, year, []) if car.year is not None else []
            if choices:
                return settle(car, IdentifyOutcome(outcome="CHOICES", need="ENGINE", choices=choices, note=str(e)))
            return settle(car, IdentifyOutcome(outcome="NEED", need="YEAR", note=str(e)))
        except NotOnSale as e:
            choices = await engines_on_sale(ports, car, year, [])
            return settle(car, IdentifyOutcome(outcome="CHOICES" if choices else "NEED", need="ENGINE",
                                               choices=choices, note=str(e)))  # fmt: skip
        except UnknownModel as e:
            names = e.closest or [f"{car.make} {m.model}" for m in lineup_models(lineup)[:MAX_NAMES]]
            names = intake.other_names(f"{car.make} {car.model}", intake.other_names(car.model, names))  # never itself
            choices = [Choice(label=n, make=car.make, model=n.removeprefix(f"{car.make} ")) for n in names]
            car.resolution, car.variant_id, car.label = "UNRESOLVED", None, None
            return settle(car, IdentifyOutcome(outcome="NOT_FOUND", need="MODEL", choices=choices, checked=e.checked))
        hint = car.constraints.engine_hint
        if hint is not None and not hint.empty() and not engine_of_fits(v, hint):
            # no version with the named engine (FR-015): offer the engines that exist, no unsourced alternatives
            choices = await engines_on_sale(ports, car, year, [])
            return settle(car, IdentifyOutcome(outcome="CHOICES" if choices else "NEED", need="ENGINE",
                                               choices=choices))  # fmt: skip
        car.variant_id, car.label, car.resolution = v.id, v.label, proposed(car)
        return settle(car, IdentifyOutcome(outcome="IDENTIFIED", note=ident.note))
