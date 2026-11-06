"""Block race: the drag race result, with the person's prediction."""

from __future__ import annotations

from dataclasses import asdict

from automind.chat.domain.assessment import dragrace


def race_block(race: dragrace.RaceResult, predicted_car_id: str | None = None) -> dict:
    """race_chart; with a user prediction it also says whether the prediction was right (US6)."""
    winner = next((r.car_id for r in race.results if r.rank == 1), None)
    return {
        "type": "race_chart",
        "prediction": predicted_car_id,
        "prediction_correct": (predicted_car_id == winner) if predicted_car_id and winner else None,
        "title": "Drag race 0–400 m",
        "model_version": race.model_version,
        "settings": asdict(race.settings),
        "series": [
            {"car_id": r.car_id, "label": r.label, "t": r.t, "v_kmh": r.v_kmh, "s_m": r.s_m} for r in race.results
        ],
        "results": [
            {
                "car_id": r.car_id,
                "label": r.label,
                "rank": r.rank,
                "t_0_100": r.t_0_100,
                "t_0_200": r.t_0_200,
                "t_400m": r.t_400m,
                "v_400m": r.v_400m,
                "claimed_0_100": r.claimed_0_100,
            }
            for r in race.results
        ],
        "excluded": race.excluded,
        "assumptions": [
            {
                "car_id": r.car_id,
                "items": [{"name": a["name"], "value": a["value"], "unit": a["unit"]} for a in r.assumptions],
            }
            for r in race.results
        ],
    }
