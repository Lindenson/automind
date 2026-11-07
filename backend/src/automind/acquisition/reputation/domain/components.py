"""Reputation of the pipeline components vector blame names (spec 011 FR-011, research R9), pure: weights of right
and wrong signals that fade with a half-life, and the lower bound of the accuracy they imply. Keys of components:
`parser:km77@v1`, `extractor:extract_specs@v3|<model>`, `rule:units.ps_kw`, `fusion:merge@1`, `relevance:<method>`."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from automind.acquisition.registry.domain.score import decay, wilson_lb


@dataclass(frozen=True)
class Weights:
    """A component's weights of right and wrong signals, faded up to `decayed_at`, and their accuracy lower bound."""

    right_w: float
    wrong_w: float
    decayed_at: datetime | None
    acc_lb: float = 0.0


def faded(w: Weights, now: datetime, half_life_days: float) -> Weights:
    """The weights faded from `decayed_at` to `now`, with the lower bound recomputed."""
    days = (now - w.decayed_at).total_seconds() / 86400 if w.decayed_at else 0.0
    right, wrong = w.right_w, w.wrong_w
    if days > 0:
        right, wrong = decay(right, days, half_life_days), decay(wrong, days, half_life_days)
    return Weights(right, wrong, now, wilson_lb(right, wrong))


def credited(w: Weights, verdict: str, weight: float, now: datetime, half_life_days: float) -> Weights:
    """A share of a signal given to the component: faded to now first, then added on its side."""
    f = faded(w, now, half_life_days)
    right, wrong = (f.right_w + weight, f.wrong_w) if verdict == "right" else (f.right_w, f.wrong_w + weight)
    return Weights(right, wrong, now, wilson_lb(right, wrong))


def mean_lb_by_kind(rows: Iterable[tuple[str, Weights]]) -> dict[str, float]:
    """Per component kind, the lower bounds averaged by weight (the `automind_component_acc_lb{kind}` gauge)."""
    by_kind: dict[str, list[tuple[float, float]]] = {}
    for kind, w in rows:
        by_kind.setdefault(kind, []).append((w.acc_lb, w.right_w + w.wrong_w))
    out: dict[str, float] = {}
    for kind, v in by_kind.items():
        total = sum(weight for _, weight in v)
        out[kind] = sum(a * weight for a, weight in v) / total if total > 0 else 0.0
    return out
