"""The worker's Prometheus exporter (contracts/task-queue.md "Metrics"), on its own port (`worker.metrics_port`, 9101).

Besides the worker families below, the worker serves every spec 010 snapshot gauge (it runs `metrics_snapshot`) and
the `automind_loop_*` health of its periodic tasks, read from the journal so that any number of workers report the
same health. The API keeps its live counters and the `retention` loop on its own /metrics.
"""

from __future__ import annotations

import contextlib
import logging
import time
from typing import Any

from prometheus_client import REGISTRY, Counter, Gauge, Histogram, start_http_server

from automind.insight.metrics import prom  # noqa: F401 - registers the 010 families (snapshot gauges, counters)

log = logging.getLogger(__name__)
P = prom.P

BEAT = Gauge(P + "worker_beat_timestamp_seconds", "Unix time of the worker's last heartbeat", ["worker"])
TASKS = Gauge(P + "acq_tasks", "Background tasks in the journal by kind and state", ["kind", "state"])
DURATION = Histogram(P + "acq_task_duration_seconds", "Run time of background tasks", ["kind"],
                     buckets=(0.1, 0.5, 1, 5, 15, 60, 300, 900, 3600))  # fmt: skip
FAILURES = Counter(P + "acq_task_failures_total", "Failed runs of background tasks", ["kind"])
# spec 011 US3 (T072): honest reputation, set by the `rollup` and `reputation_signals` tasks (7-day windows)
SEARCHES_PER_VALUE = Gauge(P + "searches_per_accepted_value", "Web searches per accepted value, last 7 days",
                           ["area"])  # fmt: skip
WRONG_SHARE = Gauge(P + "wrong_share", "Share of accepted values with a wrong signal, last 7 days", ["area"])
WRONG_SHARE_BASELINE = Gauge(P + "wrong_share_baseline", "Wrong share of the last closed KPI baseline", ["area"])
COMPONENT_ACC_LB = Gauge(P + "component_acc_lb", "Accuracy lower bound of pipeline components by kind", ["kind"])
# spec 011 US4 (T089): parser metrics over the last 7 days and drift, set by the `parser_daily` and `drift` tasks
PARSER_FIELDS = Gauge(P + "parser_fields_per_page", "Fields found per page by a parser version, last 7 days",
                      ["reader", "version"])  # fmt: skip
PARSER_PASS = Gauge(P + "parser_pass_rate", "Share of a parser version's rows passing the checks, last 7 days",
                    ["reader", "version"])  # fmt: skip
PARSER_DRIFT = Gauge(P + "parser_drift", "1 while the running version of a parser is degraded by drift", ["reader"])
# spec 011 US5 (T100, T110): the change journal and the agents' daily spend
CHANGES = Counter(P + "acq_changes", "Transitions of gated changes by agent and status", ["agent", "status"])
OPEN_CHANGES = Gauge(P + "acq_open_changes", "Open gated changes by agent and phase", ["agent", "phase"])
AGENT_SPEND = Gauge(P + "agent_spend_today_eur", "Spend of an engine agent today (its tasks and gates)", ["agent"])
AGENT_BUDGET = Gauge(P + "agent_budget_eur", "Daily budget of an engine agent (config/agents.yaml)", ["agent"])
# spec 011 T057: prefetch (cars and areas refreshed before users ask; the day's spend against its cap)
PREFETCH_VARIANTS = Counter(P + "prefetch_variants", "Cars refreshed by prefetch")
PREFETCH_AREAS = Counter(P + "prefetch_areas", "Areas refreshed by prefetch", ["area"])
PREFETCH_SPEND = Gauge(P + "prefetch_spend_today_eur", "Spend of prefetch today (all its tasks)")
PREFETCH_BUDGET = Gauge(P + "prefetch_budget_eur", "Daily budget of prefetch (acquisition.yaml prefetch.eur_per_day)")

_counts: list[tuple[str, str, int]] = []


def metric_names() -> set[str]:
    """Sample names exported only by the worker (for the rules test)."""
    d = P + "acq_task_duration_seconds"
    return {P + "worker_beat_timestamp_seconds", P + "acq_tasks", P + "acq_task_failures_total",
            d + "_bucket", d + "_sum", d + "_count", P + "searches_per_accepted_value", P + "wrong_share",
            P + "wrong_share_baseline", P + "component_acc_lb", P + "parser_fields_per_page", P + "parser_pass_rate",
            P + "parser_drift", P + "acq_changes_total", P + "acq_open_changes", P + "agent_spend_today_eur",
            P + "agent_budget_eur", P + "prefetch_variants_total", P + "prefetch_areas_total",
            P + "prefetch_spend_today_eur", P + "prefetch_budget_eur"}  # fmt: skip


def start(port: int, addr: str = "127.0.0.1") -> Any:
    """Serve /metrics; 0 = off. Returns the server (or None)."""
    if not port:
        return None
    server, _thread = start_http_server(port, addr=addr, registry=REGISTRY)
    log.info("worker metrics on http://%s:%s/metrics", addr, port)
    return server


def beat(worker_id: str, at: float | None = None) -> None:
    BEAT.labels(worker=worker_id).set(at or time.time())


def beat_timestamp() -> float:
    best = 0.0
    for metric in BEAT.collect():
        for s in metric.samples:
            best = max(best, s.value)
    return best


def set_counts(rows: list[tuple[str, str, int]]) -> None:
    global _counts
    TASKS.clear()
    for kind, state, n in rows:
        TASKS.labels(kind=kind, state=state).set(n)
    _counts = list(rows)


def task_counts() -> dict[tuple[str, str], int]:
    return {(k, s): n for k, s, n in _counts}


def observe(kind: str, seconds: float, ok: bool) -> None:
    with contextlib.suppress(Exception):
        DURATION.labels(kind=kind).observe(max(0.0, seconds))
        if not ok:
            FAILURES.labels(kind=kind).inc()


def failures(kind: str) -> float:
    for metric in FAILURES.collect():
        for s in metric.samples:
            if s.name.endswith("_total") and s.labels.get("kind") == kind:
                return float(s.value)
    return 0.0


def set_reputation(
    searches_per_value: dict[str, float], wrong_share: dict[str, float], component_acc_lb: dict[str, float],
    baseline_wrong_share: dict[str, float],
) -> None:  # fmt: skip
    for gauge, values, label in (
        (SEARCHES_PER_VALUE, searches_per_value, "area"),
        (WRONG_SHARE, wrong_share, "area"),
        (COMPONENT_ACC_LB, component_acc_lb, "kind"),
        (WRONG_SHARE_BASELINE, baseline_wrong_share, "area"),
    ):
        gauge.clear()
        for key, v in values.items():
            gauge.labels(**{label: key}).set(v)


def set_parsers(
    fields_per_page: dict[tuple[str, str], float], pass_rate: dict[tuple[str, str], float], drift: dict[str, float]
) -> None:
    for gauge, values in ((PARSER_FIELDS, fields_per_page), (PARSER_PASS, pass_rate)):
        gauge.clear()
        for (reader, version), v in values.items():
            gauge.labels(reader=reader, version=version).set(v)
    PARSER_DRIFT.clear()
    for reader, v in drift.items():
        PARSER_DRIFT.labels(reader=reader).set(v)


def set_changes(open_changes: dict[tuple[str, str], float], spend: dict[str, float],
                budgets: dict[str, float] | None = None) -> None:  # fmt: skip
    OPEN_CHANGES.clear()
    for (agent, phase), n in open_changes.items():
        OPEN_CHANGES.labels(agent=agent, phase=phase).set(n)
    for agent, eur in spend.items():
        AGENT_SPEND.labels(agent=agent).set(eur)
    for agent, eur in (budgets or {}).items():
        AGENT_BUDGET.labels(agent=agent).set(eur)
