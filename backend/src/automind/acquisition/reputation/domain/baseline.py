"""The KPI baseline before registry autonomy (spec 011 FR-014, research R7), as pure rules: the values of a window
(accuracy, searches per value, satisfaction, nodata share, coverage) from what was measured over it, and the minimum
length of a window before it closes."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TypedDict

from automind.shared.contracts.json import JsonObject

MIN_DAYS = 7  # a window closes after a week at least: one week of every weekday's traffic


class Kpis(TypedDict):
    """The daily roll-up's KPIs over a period, by area: searches per accepted value, share of wrong values."""

    searches_per_value: dict[str, float]
    wrong_share: dict[str, float]


@dataclass(frozen=True)
class Satisfaction:
    """The mean satisfaction score of the finished turns of a period (None: no turn), and how many there were."""

    mean: float | None
    turns: int


class BaselineValues(TypedDict):
    """The values a window records (JSON in `kpi_baselines.values`; the gauges read `accuracy_share_wrong`)."""

    accuracy_share_wrong: dict[str, float]
    searches_per_value: dict[str, float]
    satisfaction_index: float | None
    turns: int
    nodata_share: dict[str, float]  # area -> share of reports with an area without data
    coverage: float | None  # share of reports without any area without data; None: no report
    reports: int
    days: float


def baseline_values(kpis: Kpis, satisfaction: Satisfaction, report_signals: Sequence[JsonObject], start: datetime,
                    end: datetime) -> BaselineValues:  # fmt: skip
    """The window's values over [start, end]; `report_signals` are the outcome signals of its reports, whose
    `nodata_items` name the areas left without data."""
    per_area: dict[str, int] = defaultdict(int)
    with_gap = 0
    for signals in report_signals:
        areas = {i.get("area") for i in signals.get("nodata_items") or [] if i.get("area")}
        with_gap += 1 if areas else 0
        for a in areas:
            per_area[str(a)] += 1
    n = len(report_signals)
    return {
        "accuracy_share_wrong": kpis["wrong_share"],
        "searches_per_value": kpis["searches_per_value"],
        "satisfaction_index": satisfaction.mean,
        "turns": satisfaction.turns,
        "nodata_share": {a: c / n for a, c in sorted(per_area.items())} if n else {},
        "coverage": 1 - with_gap / n if n else None,
        "reports": n,
        "days": round((end - start).total_seconds() / 86400, 2),
    }


def days_run(started_at: datetime, now: datetime) -> float:
    """How long a window has run, in days."""
    return (now - started_at).total_seconds() / 86400


def may_close(started_at: datetime, now: datetime) -> bool:
    """A window may close once it has run `MIN_DAYS`."""
    return now - started_at >= timedelta(days=MIN_DAYS)
