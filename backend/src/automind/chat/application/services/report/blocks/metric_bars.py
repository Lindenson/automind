"""Block metric_bars: the derived metrics of each car as bars."""

from __future__ import annotations

from automind.chat.application.services.report.facts.scoring_inputs import car_facts
from automind.chat.domain.assessment import metrics as scoring


def metric_bars(cars: list[dict]) -> dict:
    ms = {c["variant"].id: scoring.metrics(car_facts(c)) for c in cars}
    defs = [
        ("power_to_weight", "Power-to-weight", "kW/t", "higher"),
        ("weight_to_power", "Weight-to-power", "kg/kW", "lower"),
        ("torque_to_weight", "Torque-to-weight", "N·m/t", "higher"),
        ("specific_output", "Specific output", "kW/L", "higher"),
    ]
    return {
        "type": "metric_bars",
        "title": "Derived metrics (computed)",
        "metrics": [
            {
                "key": k,
                "label": lbl,
                "unit": u,
                "better": b,
                "values": [
                    {"car_id": c["variant"].id, "label": c["variant"].label, "value": ms[c["variant"].id][k]}
                    for c in cars
                ],
            }
            for k, lbl, u, b in defs
            if any(ms[c["variant"].id][k] is not None for c in cars)
        ],
    }
