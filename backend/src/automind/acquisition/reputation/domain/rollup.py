"""The daily roll-up (spec 011 T072, research R7, SC-009), pure: one `acq_daily` row per day, area and market from the
day's attempts, searches and truth signals, and the KPIs over a period.

- `searches`  searches not served from the cache, under market `*` (they carry no market), plus the attempts'
  searches per market
- `pages`, `accepted_values`, `cost_eur`, `explore_eur` (candidates' attempts)  from the registry attempts
- `wrong_values`, `gold_checked`, `gold_wrong`  from the truth signals"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TypedDict

ANY_MARKET = "*"


class Kpis(TypedDict):
    """The roll-up's KPIs over a period, by area: searches per accepted value, share of wrong values."""

    searches_per_value: dict[str, float]
    wrong_share: dict[str, float]


@dataclass(frozen=True)
class AttemptCounts:
    """A day's registry attempts of one area and market."""

    area: str
    market: str
    pages: int
    accepted_values: int
    searches: int
    cost_eur: float
    explore_eur: float


@dataclass(frozen=True)
class SearchCounts:
    """A day's searches of one area that were not served from the cache."""

    area: str
    searches: int
    cost_eur: float


@dataclass(frozen=True)
class SignalCounts:
    """A day's truth signals of one area and market: distinct wrong values, gold checks and gold wrongs."""

    area: str
    market: str
    wrong_values: int
    gold_checked: int
    gold_wrong: int


@dataclass(frozen=True)
class AreaTotals:
    """An area's sums over a period: searches, accepted values, wrong values."""

    area: str
    searches: float
    accepted_values: float
    wrong_values: float


class DailyValues(TypedDict):
    """One `acq_daily` row's values."""

    searches: int
    pages: int
    accepted_values: int
    wrong_values: int
    gold_checked: int
    gold_wrong: int
    cost_eur: float
    explore_eur: float


_COUNTS = ("searches", "pages", "accepted_values", "wrong_values", "gold_checked", "gold_wrong")


def daily_rows(attempts: Iterable[AttemptCounts], searches: Iterable[SearchCounts],
               signals: Iterable[SignalCounts]) -> dict[tuple[str, str], DailyValues]:  # fmt: skip
    """The day's rows by (area, market)."""
    rows: dict[tuple[str, str], dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for a in attempts:
        r = rows[(a.area, a.market)]
        r["pages"] += a.pages
        r["accepted_values"] += a.accepted_values
        r["searches"] += a.searches
        r["cost_eur"] += a.cost_eur
        r["explore_eur"] += a.explore_eur
    for s in searches:
        r = rows[(s.area, ANY_MARKET)]
        r["searches"] += s.searches
        r["cost_eur"] += s.cost_eur
    for g in signals:
        r = rows[(g.area, g.market)]
        r["wrong_values"] += g.wrong_values
        r["gold_checked"] += g.gold_checked
        r["gold_wrong"] += g.gold_wrong
    return {key: _values(r) for key, r in rows.items()}


def kpis_of(totals: Iterable[AreaTotals]) -> Kpis:
    """Searches per accepted value and wrong share by area (areas without accepted values are left out)."""
    spv: dict[str, float] = {}
    wrong: dict[str, float] = {}
    for t in totals:
        if t.accepted_values:
            spv[t.area] = float(t.searches) / float(t.accepted_values)
            wrong[t.area] = float(t.wrong_values) / float(t.accepted_values)
    return {"searches_per_value": spv, "wrong_share": wrong}


def _values(r: dict[str, float]) -> DailyValues:
    counts = {k: int(r.get(k, 0)) for k in _COUNTS}
    return {
        "searches": counts["searches"], "pages": counts["pages"], "accepted_values": counts["accepted_values"],
        "wrong_values": counts["wrong_values"], "gold_checked": counts["gold_checked"],
        "gold_wrong": counts["gold_wrong"], "cost_eur": round(r.get("cost_eur", 0.0), 4),
        "explore_eur": round(r.get("explore_eur", 0.0), 4),
    }  # fmt: skip
