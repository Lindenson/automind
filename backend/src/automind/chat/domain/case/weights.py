"""The person adjusting criteria weights by hand (spec 007): `set_weights`."""

from __future__ import annotations

from automind.chat.domain.case.casefile import CaseFile
from automind.chat.domain.case.enums import CRITERION_KEYS


def set_weights(case: CaseFile, raw: dict[str, float]) -> CaseFile:
    """User weight edit (FR-026): validate keys, reject negatives, normalize to 100."""
    unknown = [k for k in raw if k not in CRITERION_KEYS]
    if unknown:
        raise ValueError(f"unknown criteria: {', '.join(unknown)}")
    if any(v < 0 for v in raw.values()):
        raise ValueError("weights must be ≥ 0")
    total = sum(raw.values())
    if total <= 0:
        raise ValueError("at least one weight must be > 0")
    c = case.model_copy(deep=True)
    c.weights = {k: round(v * 100 / total, 4) for k, v in raw.items()}
    c.weights_overridden = True
    return c
