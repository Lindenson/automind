"""Prometheus metrics of spec 010 (contracts/metrics.md).

Live counters and histograms are incremented where things happen (turn end, model callback, search, fetch,
feedback, registry). Slow values (KPIs, source scores, loop health) live in a `Snapshot` refreshed in the background;
the collector only reads the last snapshot, so a scrape never touches the database (FR-031).

The app runs one process (ADR-026), so the default registry is correct.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any

from prometheus_client import REGISTRY, Counter, Histogram, disable_created_metrics
from prometheus_client.core import GaugeMetricFamily
from prometheus_client.registry import Collector

log = logging.getLogger(__name__)

P = "automind_"
disable_created_metrics()  # type: ignore[no-untyped-call]  # no *_created samples

TURNS = Counter(P + "turns_total", "Turns by kind of request, status and action", ["kind", "status", "action"])
TURN_DURATION = Histogram(
    P + "turn_duration_seconds", "Turn duration", ["kind"], buckets=(1, 3, 10, 30, 60, 120, 300, 600, 1200)
)
TURN_FAILURES = Counter(P + "turn_failures_total", "Failure classes of turns", ["class"])
FEEDBACK = Counter(P + "feedback_total", "User feedback by kind", ["kind"])
WRONG_VALUES = Counter(P + "wrong_values_total", "Values shown wrong, by kind of data and blamed component",
                       ["area", "blame"])  # fmt: skip
LLM_CALLS = Counter(P + "llm_calls_total", "Model calls", ["role", "model", "fallback"])
LLM_ERRORS = Counter(P + "llm_errors_total", "Model call errors", ["role", "kind"])
LLM_COST = Counter(P + "llm_cost_eur_total", "Model spend in euros", ["role"])
SEARCH_CALLS = Counter(P + "search_calls_total", "Search calls", ["provider", "cached", "ok"])
FETCH = Counter(P + "fetch_total", "Page fetches by outcome", ["outcome"])
RESEARCH_JOBS = Counter(P + "research_jobs_total", "Research jobs by area and status", ["area", "status"])
REGISTRY_ATTEMPTS = Counter(P + "registry_attempts_total", "Source attempts", ["area", "outcome"])
REGISTRY_CHANGES = Counter(P + "registry_changes_total", "Registry changes", ["change", "author"])

_COUNTERS: dict[str, Any] = {
    "turns": TURNS, "turn_failures": TURN_FAILURES, "feedback": FEEDBACK, "wrong_values": WRONG_VALUES,
    "llm_calls": LLM_CALLS, "llm_errors": LLM_ERRORS, "search_calls": SEARCH_CALLS, "fetch": FETCH,
    "research_jobs": RESEARCH_JOBS, "registry_attempts": REGISTRY_ATTEMPTS, "registry_changes": REGISTRY_CHANGES,
}  # fmt: skip


def inc(name: str, amount: float = 1.0, **labels: Any) -> None:
    """Increment a counter by short name; never raises (metrics must not break a turn)."""
    try:
        c = _COUNTERS[name]
        (c.labels(**{k: str(v) for k, v in labels.items()}) if labels else c).inc(amount)
    except Exception:  # noqa: BLE001
        log.debug("metric %s not incremented", name, exc_info=True)


def observe_turn(kind: str | None, seconds: float) -> None:
    try:
        TURN_DURATION.labels(kind=kind or "unknown").observe(max(0.0, seconds))
    except Exception:  # noqa: BLE001
        log.debug("turn duration not observed", exc_info=True)


def add_cost(role: str, eur: float) -> None:
    try:
        if eur:
            LLM_COST.labels(role=role).inc(max(0.0, float(eur)))
    except Exception:  # noqa: BLE001
        log.debug("cost not counted", exc_info=True)


# --- snapshot gauges --------------------------------------------------------------------------------------------


@dataclass
class Gauge:
    name: str
    help: str
    labels: tuple[str, ...]
    samples: list[tuple[tuple[str, ...], float]] = field(default_factory=list)


GAUGES: dict[str, tuple[str, tuple[str, ...]]] = {
    "satisfaction_index": ("Satisfaction index 0-1 per kind of request", ("kind", "window")),
    "satisfaction_turns": ("Turns behind the satisfaction index", ("kind", "window")),
    "satisfaction_index_by": ("Satisfaction index per language or persona", ("dim", "key", "window")),
    "accuracy_share": ("Share of right truth signals per kind of data", ("area", "window")),
    "accuracy_signals": ("Weighted truth signals per kind of data", ("area", "window")),
    "nodata_share": ("Share of turns with no data for a kind of data", ("area", "window")),
    "complaints_24h": ("Complaint feedback in the last 24 h", ("kind",)),
    "complaints_daily_avg_30d": ("Average daily complaint feedback over 30 days", ("kind",)),
    "capabilities": ("Source capabilities by status", ("area", "status")),
    "active_sources": ("Active sources per kind of data and market", ("area", "market")),
    "source_score": ("Quality score of a source capability", ("domain", "area", "market")),
    "source_accuracy_lb": ("Lower bound of a source capability's accuracy", ("domain", "area", "market")),
    "source_yield": ("Yield of a source capability", ("domain", "area", "market")),
    "source_wrong_values_24h": ("Wrong values from a source in 24 h", ("domain",)),
    "reader_zero_streak": ("Consecutive empty pages of a site reader", ("reader",)),
    "llm_fallback_share": ("Share of model calls answered by a fallback model", ("role", "window")),
    "provider_unavailable_seconds": ("Seconds a model provider has been unavailable", ("provider",)),
    "spend_today_eur": ("Spend today in euros", ()),
    "daily_cap_eur": ("Daily spend cap in euros", ()),
    "background_spend_today_eur": ("Background spend today in euros", ("loop",)),
    "background_budget_eur": ("Daily background budget in euros", ("loop",)),
    "loop_last_success_timestamp_seconds": ("Unix time of the last successful run of a background loop", ("loop",)),
    "loop_fails_in_row": ("Consecutive failed runs of a background loop", ("loop",)),
    "loop_interval_seconds": ("Expected interval between runs of a background loop", ("loop",)),
    "issues": ("Insight issues by component and status", ("component", "status")),
}


@dataclass
class Snapshot:
    values: dict[str, list[tuple[tuple[str, ...], float]]] = field(default_factory=dict)

    def set(self, name: str, labels: Iterable[str], value: float) -> None:
        self.values.setdefault(name, []).append((tuple(str(x) for x in labels), float(value)))


_LAST = Snapshot()


def publish(snap: Snapshot) -> None:
    """Replace the served snapshot (loop heartbeats are merged in by the collector)."""
    global _LAST
    _LAST = snap


class SnapshotCollector(Collector):
    def collect(self) -> Iterator[GaugeMetricFamily]:
        from automind.insight.metrics import heartbeat  # noqa: PLC0415

        values = dict(_LAST.values)
        for name, rows in heartbeat.samples().items():
            values[name] = rows
        for name, (help_, labels) in GAUGES.items():
            fam = GaugeMetricFamily(P + name, help_, labels=list(labels))
            for lv, v in values.get(name, []):
                fam.add_metric(list(lv), v)
            yield fam

    def describe(self) -> Iterator[GaugeMetricFamily]:
        for name, (help_, labels) in GAUGES.items():
            yield GaugeMetricFamily(P + name, help_, labels=list(labels))


_COLLECTOR = SnapshotCollector()
with contextlib.suppress(ValueError):  # re-imported in tests
    REGISTRY.register(_COLLECTOR)


def metric_names() -> set[str]:
    """Every exported sample name (for the rules test, FR-032)."""
    out = {P + n for n in GAUGES}
    for c in _COUNTERS.values():
        out.add(c._name + "_total")  # noqa: SLF001 - prometheus_client strips the _total suffix
    out.add(LLM_COST._name + "_total")  # noqa: SLF001
    base = P + "turn_duration_seconds"
    out |= {base + "_bucket", base + "_sum", base + "_count"}
    return out
