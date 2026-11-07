"""Stage place_market: where a car is sold (chat 2026-11-06: Deepal S09, Li Auto L9). A car not on the Spanish
line-up (a make not sold in Spain, or a model its Spanish line-up and the catalogue lack) is looked up where it is
sold — Europe first, then the make's home market, then anywhere — and identified there (`CaseCar.market`); an
identified car not sold in Spain says where its data and prices come from (spec 009 FR-009)."""

from __future__ import annotations

from automind.chat.application.ports import Ports
from automind.chat.application.services.identification.contracts import KnownModels, Lineup, LineupLookup
from automind.chat.application.services.identification.stages.normalise_name import match_model
from automind.chat.domain.case import CaseCar, IdentifyOutcome
from automind.chat.domain.identification.variant_match import same_model
from automind.chat.domain.intake import LineupModel
from automind.shared.contracts.config import MakeNames
from automind.shared.vehicle import markets


async def place_on_market(ports: Ports, car: CaseCar, lookup: LineupLookup | None,
                          names: KnownModels) -> Lineup | None:  # fmt: skip
    """Sets `car.market` (None: Spain) and returns the line-up to identify with: the one that lists the model, else
    one of the make's (its models are the nearest ones)."""
    reg, lineup = ports.ref.makes, names.lineup
    in_spain = reg is None or reg.sold_in_spain(car.make)
    car.market = None
    if in_spain and (lineup is None or listed(lineup, car.model) or car.model in names.catalog):
        return lineup
    market, there = await where_sold(ports, car, reg, lookup)
    # a make not sold in Spain is of its home market even when no line-up names the model
    home = reg.home(car.make) if reg is not None else None
    car.market = market or (None if in_spain else home or markets.ANYWHERE)
    if market == markets.EUROPE:  # the European country whose page lists it, when its domain says ("PL")
        car.market = next((m.country for m in lineup_models(there) if m.country and _listed_as(m, car.model)),
                          markets.EUROPE)  # fmt: skip
    if there is None:
        return lineup
    if market is not None:
        match_model(car, reg, names.known | {m.model for m in lineup_models(there)})
    return there


async def where_sold(ports: Ports, car: CaseCar, reg: MakeNames | None, lookup: LineupLookup | None,
                     any_model: bool = False) -> tuple[str | None, Lineup | None]:  # fmt: skip
    """The first market whose line-up lists the car's model (any model with `any_model`): Europe, then the make's
    home market, then anywhere (markets.lookup_markets). When none lists it: (None, the first line-up found),
    whose models are the nearest ones to offer."""
    if lookup is None or not car.make:
        return None, None
    first: Lineup | None = None
    for market in markets.lookup_markets(reg.home(car.make) if reg is not None else None):
        try:
            lu = await lookup(ports, car.make, market=market)
        except Exception:  # noqa: BLE001 - a failed look-up never blocks the intake
            lu = None
        if lu is not None and (listed(lu, car.model) if not any_model else bool(lineup_models(lu))):
            return market, lu
        first = first if first is not None or not lineup_models(lu) else lu
    return None, first


def say_where_sold(car: CaseCar, o: IdentifyOutcome) -> IdentifyOutcome:
    """An identified car not sold in Spain says where its data and prices come from (spec 009 FR-009)."""
    if car.market is not None and o.outcome == "IDENTIFIED":
        kind = markets.market_note(car.market)
        if not any(e.get("kind") == kind for e in o.events):
            o.events.append({"kind": kind, "market": car.market})
    return o


def listed(lineup: Lineup | None, model: str | None) -> bool:
    """The line-up lists the model (in any of its spellings)."""
    return any(_listed_as(m, model) for m in lineup_models(lineup))


def lineup_models(lineup: Lineup | None) -> list[LineupModel]:
    """The models of a line-up ([] without one)."""
    return list(lineup.models) if lineup is not None else []


def _listed_as(m: LineupModel, model: str | None) -> bool:
    return same_model(model, m.model) or same_model(m.model, model)
