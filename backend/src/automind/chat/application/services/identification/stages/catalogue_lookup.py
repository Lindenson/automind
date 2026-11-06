"""Stage catalogue_lookup: the models known for the car's make — the catalogue, config/generations.yaml and the
make's line-up (Spain; for a make not sold in Spain, where it is sold) — and the model the person named matched
to one of them (spec 005 R2, FR-007)."""

from __future__ import annotations

from automind.chat.application.ports import Ports
from automind.chat.application.services.identification.catalogue import known_models
from automind.chat.application.services.identification.contracts import KnownModels, LineupLookup
from automind.chat.application.services.identification.stages.normalise_name import match_model
from automind.chat.application.services.identification.stages.place_market import lineup_models, where_sold
from automind.chat.domain.case import CaseCar


async def catalogue_lookup(ports: Ports, car: CaseCar, lookup: LineupLookup | None) -> KnownModels:
    reg = ports.ref.makes
    in_spain = reg is None or reg.sold_in_spain(car.make)
    lineup = await lookup(ports, car.make) if lookup is not None and in_spain else None
    catalog = set(await known_models(car.make or "", ports.ref))
    known = catalog | {m.model for m in lineup_models(lineup)}
    match_model(car, reg, known)
    if not car.model and not in_spain:  # a make not sold in Spain: its models where it is sold
        _, lineup = await where_sold(ports, car, reg, lookup, any_model=True)
        known |= {m.model for m in lineup_models(lineup)}
        match_model(car, reg, known)
    return KnownModels(lineup, catalog, known)
