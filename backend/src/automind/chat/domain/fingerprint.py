"""The fingerprint of a case: a hash of everything a report depends on (FR-004), in two parts "data:params" (spec 007
FR-012), so a report is never repeated unchanged and a panel edit knows whether only the assessment changed."""

from __future__ import annotations

import hashlib
import json

from automind.chat.domain.case import CaseFile


def fingerprint(case: CaseFile) -> str:
    """Hash of everything a report depends on (FR-004), in two parts "data:params" (spec 007 FR-012). A stored
    fingerprint from before spec 007 has no ":" and counts as different in both parts."""
    return f"{fingerprint_data(case)}:{fingerprint_params(case)}"


def fingerprint_data(case: CaseFile) -> str:
    """What the data of a report depends on: the cars (spec 007 FR-012)."""
    return _hash({
        "cars": [[c.variant_id, c.condition, c.year, c.mileage_km] for c in case.cars],
        "race": case.race_settings.model_dump() if case.race_settings else None,
        "prediction": case.prediction.winner_key if case.prediction else None,
        "level": case.compare_level,
    })  # fmt: skip


def fingerprint_params(case: CaseFile) -> str:
    """What the assessment depends on: who the user is and what matters (spec 007 FR-012; before, family, style,
    region and the ownership period were missing, so a profile change looked like "nothing new")."""
    p = case.profile
    return _hash({
        "persona": case.persona,
        "profile": [p.age, p.family, p.age_band, p.driving_style, p.region, p.climate, p.annual_km_min,
                    p.annual_km_max] + ([p.home_charging] if p.home_charging != "UNKNOWN" else []),
        "ownership_years": case.ownership_years,
        "priorities": sorted((x.criterion, x.strength) for x in case.priorities),
        "weights": sorted((k, round(v, 2)) for k, v in case.weights.items()),
        "adjustments": sorted((k, round(v, 2)) for k, v in case.weight_adjustments.items()),
        "excluded": sorted(case.weights_excluded),
        "usage": sorted(case.usage),
        "budget": [case.budget.max_eur, case.budget.intent, case.budget.currency, case.budget.kind],
        "running": case.running_cost_limit.model_dump() if case.running_cost_limit else None,
        "needs": case.needs.model_dump(),
        "annual_km": case.annual_km,
        "rates": case.rates_override.model_dump(exclude_none=True),
    })  # fmt: skip


def _hash(payload: object) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:16]
