"""Quality of a source for a kind of data (spec 010 US6, research R9). Pure.

yield    = (accepted + 1) / (attempts + 2)
accuracy = right / (right + wrong), with pseudo-counts by source type (the prior)
acc_lb   = Wilson lower bound of the accuracy: few signals → low bound, so a lucky newcomer cannot outrank a proven
           source
score    = acc_lb × yield − λ × € per attempt
Signals and counts fade with a half-life (applied by the caller through `decay`).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Counts:
    attempts: float = 0.0
    accepted: float = 0.0
    right_w: float = 0.0
    wrong_w: float = 0.0
    cost_eur: float = 0.0


@dataclass(frozen=True)
class Quality:
    score: float
    acc_mean: float
    acc_lb: float
    yield_: float


def decay(value: float, days: float, half_life_days: float) -> float:
    if days <= 0 or half_life_days <= 0:
        return value
    return float(value * 0.5 ** (days / half_life_days))


def wilson_lb(right: float, wrong: float, z: float = 1.96) -> float:
    n = right + wrong
    if n <= 0:
        return 0.0
    p = right / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, (centre - margin) / (1 + z * z / n))


def score_of(c: Counts, source_type: str, cfg: Mapping[str, Any]) -> Quality:
    priors: Mapping[str, Any] = cfg.get("priors") or {}
    pr, pw = priors.get(source_type) or priors.get("OTHER") or [1.0, 1.0]
    right, wrong = c.right_w + float(pr), c.wrong_w + float(pw)
    acc_mean = right / (right + wrong)
    acc_lb = wilson_lb(right, wrong, float(cfg.get("wilson_z", 1.96)))
    yld = (c.accepted + 1) / (c.attempts + 2)
    per_attempt = c.cost_eur / c.attempts if c.attempts > 0 else 0.0
    score = acc_lb * yld - float(cfg.get("cost_lambda", 2.0)) * per_attempt
    return Quality(round(score, 6), round(acc_mean, 6), round(acc_lb, 6), round(yld, 6))
