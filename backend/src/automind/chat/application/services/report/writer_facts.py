"""The compact, validated facts the writer is given (numbers come only from here, constitution III)."""

from __future__ import annotations

from automind.chat.application.services.report.facts.car import relevant
from automind.chat.application.services.report.facts.display import TABLE_ROWS, display
from automind.chat.application.services.report.facts.scoring_inputs import car_facts
from automind.chat.domain.assessment import dragrace
from automind.chat.domain.assessment import metrics as scoring
from automind.chat.domain.assessment.criteria import CriteriaScore


def summary_for_llm(cars: list[dict], race: dragrace.RaceResult, criteria: CriteriaScore | None = None) -> dict:
    """Compact, validated facts for the analyst/hub prompt (numbers come only from here)."""
    out = {
        "cars": [],
        "race": {
            "model_version": race.model_version,
            "results": [
                {
                    "label": r.label,
                    "rank": r.rank,
                    "t_0_100": r.t_0_100,
                    "t_400m": r.t_400m,
                    "v_400m": r.v_400m,
                    "claimed_0_100": r.claimed_0_100,
                }
                for r in race.results
            ],
            "excluded": race.excluded,
        },
        "criteria_scores": _criteria_facts(criteria),
    }
    for c in cars:
        vals = {}
        for k in TABLE_ROWS:
            sv = c["values"].get(k)
            if sv is not None and sv.available:
                vals[k] = {"value": display(k, sv), "confidence": sv.confidence, "provenance": sv.provenance}
        out["cars"].append(
            {
                "label": c["variant"].label,
                "powertrain": c["variant"].powertrain,
                "specs": vals,
                "metrics": scoring.metrics(car_facts(c)),
                "missing": [k for k in TABLE_ROWS if k not in vals and relevant(k, c["variant"].powertrain)],
            }
        )

    return out


def _criteria_facts(sc: CriteriaScore | None) -> dict | None:
    if sc is None:
        return None
    return {
        "note": "0–100 indices (scores), not measurements. Totals use only `compared_on` (criteria every car has "
        "data for). `tie`: no winner — say the cars are close. Differences under 5 points in one criterion are not "
        "a win; never present a few litres or a few tenths as an advantage.",
        "weights": {k: round(w, 1) for k, w in sc.weights.items()},
        "winner": next((c.label for c in sc.cars if c.car_id == sc.winner_car_id), None),
        "compared_on": list(sc.common),
        "tie": sc.tie,
        "cars": [
            {
                "label": c.label,
                "total": c.total,
                "ranked": c.ranked,
                "coverage": c.coverage,
                "parts": {k: {"score": p.score, "inputs": p.inputs} for k, p in c.parts.items()},
            }
            for c in sc.cars
        ],
    }
