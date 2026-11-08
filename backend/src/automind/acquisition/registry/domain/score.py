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
from dataclasses import dataclass

from automind.acquisition.registry.domain.config import ScoreConfig


@dataclass(frozen=True)
class Counts:
    """A capability's faded counts: attempts, accepted values, right and wrong signal weight, money spent."""

    attempts: float = 0.0
    accepted: float = 0.0
    right_w: float = 0.0
    wrong_w: float = 0.0
    cost_eur: float = 0.0


@dataclass(frozen=True)
class Quality:
    """The score and its parts (rounded to 6 places as stored)."""

    score: float
    acc_mean: float
    acc_lb: float
    yield_: float


def decay(value: float, days: float, half_life_days: float) -> float:
    """`value` faded over `days` with the half-life (unchanged for no time or no half-life)."""
    if days <= 0 or half_life_days <= 0:
        return value
    return float(value * 0.5 ** (days / half_life_days))


def wilson_lb(right: float, wrong: float, z: float = 1.96) -> float:
    """The Wilson lower bound of right / (right + wrong); 0 without signals."""
    n = right + wrong
    if n <= 0:
        return 0.0
    p = right / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, (centre - margin) / (1 + z * z / n))


def score_of(c: Counts, source_type: str, cfg: ScoreConfig) -> Quality:
    """The quality of a capability whose source is of `source_type` (its prior is added to the signals)."""
    pr, pw = cfg.prior(source_type)
    right, wrong = c.right_w + pr, c.wrong_w + pw
    acc_mean = right / (right + wrong)
    acc_lb = wilson_lb(right, wrong, cfg.wilson_z)
    yld = (c.accepted + 1) / (c.attempts + 2)
    per_attempt = c.cost_eur / c.attempts if c.attempts > 0 else 0.0
    score = acc_lb * yld - cfg.cost_lambda * per_attempt
    return Quality(round(score, 6), round(acc_mean, 6), round(acc_lb, 6), round(yld, 6))
