"""Turn cost estimate before research (FR-041, research R12). Pure and monotonic.

estimate = Σ jobs (avg input tokens × €/M in + avg output tokens × €/M out + avg searches × €/search)
           × (1 + rounds × FOLLOWUP_SHARE)

Averages are learned per area from recorded usage; until enough history exists, defaults apply.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

FOLLOWUP_SHARE = 0.5  # share of jobs expected to need each follow-up round


@dataclass(frozen=True)
class AreaAverage:
    llm_in: float
    llm_out: float
    searches: float


@dataclass(frozen=True)
class CostPrices:
    eur_per_m_in: float
    eur_per_m_out: float
    eur_per_search: float


def job_cost(avg: AreaAverage, prices: CostPrices) -> float:
    return (
        avg.llm_in * prices.eur_per_m_in / 1e6
        + avg.llm_out * prices.eur_per_m_out / 1e6
        + avg.searches * prices.eur_per_search
    )


def estimate(
    jobs: Iterable[tuple[str, str]],
    *,
    rounds: int,
    averages: Mapping[str, AreaAverage],
    default: AreaAverage,
    prices: CostPrices,
) -> float:
    """Jobs are (variant_id, area). Returns € rounded to 4 decimals."""
    base = sum(job_cost(averages.get(area, default), prices) for _, area in jobs)
    return round(base * (1 + rounds * FOLLOWUP_SHARE), 4)
