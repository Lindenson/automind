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

_counts: list[tuple[str, str, int]] = []


def metric_names() -> set[str]:
    """Sample names exported only by the worker (for the rules test)."""
    d = P + "acq_task_duration_seconds"
    return {P + "worker_beat_timestamp_seconds", P + "acq_tasks", P + "acq_task_failures_total",
            d + "_bucket", d + "_sum", d + "_count"}  # fmt: skip


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
