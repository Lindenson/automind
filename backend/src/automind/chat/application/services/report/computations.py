"""The computations of a turn kept with their inputs, assumptions and versions (constitution IX): the ownership-cost
estimates and the race simulation, through the `ComputationStore` port."""

from __future__ import annotations

from dataclasses import asdict

from automind.chat.application.ports import ComputationStore
from automind.chat.application.services.report.facts.race import race_inputs
from automind.chat.domain.assessment import dragrace
from automind.chat.domain.cost import tco


async def persist_computations(
    store: ComputationStore,
    turn_id: str,
    estimates: list[tco.TcoEstimate],
    cars: list[dict],
    race: dragrace.RaceResult | None,
    rates: dict,
    prediction: dict | None,
    mileage: dict[str, int | None],
) -> None:
    """Store TCO estimates and the race simulation of a turn (inputs, assumptions, versions; constitution IX)."""
    rows = [
        {
            "variant_id": e.car_id,
            "condition": e.condition,
            "age_years": e.age_years,
            "mileage_km": mileage.get(e.car_id),
            "annual_km": e.annual_km,
            "rates": rates,
            "items": [{k: v for k, v in asdict(i).items() if k != "estimate"} for i in e.items],
            "annual_total": e.annual_total,
            "five_year_total": e.five_year_total,
            "rules_version": e.rules_version,
        }
        for e in estimates
    ]
    simulation = None
    if race is not None and race.results:
        simulation = {
            "model_version": race.model_version,
            "settings": asdict(race.settings),
            "prediction": prediction,
            "inputs": [asdict(race_inputs(c)) for c in cars],
            "assumptions": [{"car_id": r.car_id, "items": r.assumptions} for r in race.results],
            "results": [
                {
                    "car_id": r.car_id,
                    "rank": r.rank,
                    "t_0_100": r.t_0_100,
                    "t_0_200": r.t_0_200,
                    "t_400m": r.t_400m,
                    "v_400m": r.v_400m,
                }
                for r in race.results
            ],
            "input_hash": race.input_hash,
        }
    await store.record(turn_id, rows, simulation)
