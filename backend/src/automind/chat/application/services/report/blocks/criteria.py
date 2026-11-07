"""Block criteria: the criteria scores with their weights and the relative position of each car."""

from __future__ import annotations

from typing import Any

from automind.chat.domain.assessment.criteria import CriteriaModel, CriteriaScore
from automind.shared.contracts.json import JsonObject


def criteria_block(sc: CriteriaScore, model: CriteriaModel, unmapped: list[str], breakdown: Any = None) -> JsonObject:
    """criteria_scores (contracts/chat-protocol.md): 0–100 scores computed from the sourced data, with the data each
    one is built from (per criterion and per car); each weight with its reasons (spec 007 FR-011)."""
    lines = breakdown.lines if breakdown is not None else {}
    return {
        "type": "criteria_scores",
        "title": "Criteria and scores (0–100, computed from the sourced data)",
        "criteria_version": sc.criteria_version,
        "criteria": [
            {
                "key": k,
                "label": model.criteria[k].label,
                "weight": round(w, 1),
                "definition": model.criteria[k].definition,
                "inputs": list(model.criteria[k].inputs),
                "reasons": [{"code": c, "points": p} for c, p in lines[k].contributions] if k in lines else [],
                "manual": lines[k].manual if k in lines else 0.0,
            }
            for k, w in sorted(sc.weights.items(), key=lambda x: -x[1])
        ],
        "manual_weights": bool(breakdown.manual) if breakdown is not None else False,
        "cars": [
            {
                "car_id": c.car_id,
                "label": c.label,
                "ranked": c.ranked,
                "total": c.total,
                "coverage": c.coverage,
                "parts": {
                    k: {"score": p.score, "insufficient": p.insufficient, "inputs": p.inputs}
                    for k, p in c.parts.items()
                },
            }
            for c in sc.cars
        ],
        "winner_car_id": sc.winner_car_id,
        "unmapped_wishes": list(unmapped),
        "compared_on": list(sc.common),
        "tie": sc.tie,
        # spec 004 FR-010: the basis of each score: relative to the best compared car (= 100) and what could
        # not be compared because a car has no data for it
        "relative": _relative(sc),
        "not_compared": sorted(k for k in sc.weights if sc.weights[k] > 0 and k not in sc.common),
        "single": len(sc.cars) == 1,
    }


def _relative(sc: CriteriaScore) -> dict[str, dict[str, float]]:
    """Per criterion: each car's score relative to the best compared car (best = 100)."""
    out: dict[str, dict[str, float]] = {}
    if len(sc.cars) < 2:
        return out
    for k in sc.weights:
        scores = {c.car_id: s for c in sc.cars if k in c.parts and (s := c.parts[k].score) is not None}
        best = max(scores.values(), default=None)
        if best and len(scores) >= 2:
            out[k] = {cid: round(100 * (v or 0) / best, 0) for cid, v in scores.items()}
    return out
