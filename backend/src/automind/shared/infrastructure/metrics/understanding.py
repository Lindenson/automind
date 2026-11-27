"""Prometheus metrics of the understanding step (spec 013 T036). Every function never raises: a metric must not break
a turn. Shares are ratios in the queries (e.g. overrides by rule over turns understood).

- `automind_understanding_turns_total{source,outcome}` — turns the new understanding read: `ok` or `refused`;
- `automind_understanding_overrides_total{rule}` — corrections by the IntentResolver's rule;
- `automind_understanding_dropped_total{check}` — parts of the model's reading the checks dropped;
- `automind_understanding_question_repeated_total` — turns whose open question was open at the previous turn too;
- `automind_understanding_seconds{path}` — the understanding step, `old` (interpreter) and `new` (understander), for
  the +20 % p95 criterion (G4);
- `automind_understanding_record_errors_total` — turn records the `UnderstandingLog` could not store.
"""

from __future__ import annotations

import logging

from prometheus_client import Counter, Histogram

log = logging.getLogger(__name__)

P = "automind_"
TURNS = Counter(P + "understanding_turns_total", "Turns read by the new understanding, by source and outcome",
                ["source", "outcome"])  # fmt: skip
OVERRIDES = Counter(P + "understanding_overrides_total", "IntentResolver corrections, by rule", ["rule"])
DROPPED = Counter(P + "understanding_dropped_total", "Parts of a model reading dropped by a check", ["check"])
REPEATED = Counter(P + "understanding_question_repeated_total", "Turns whose open question was already open")
SECONDS = Histogram(P + "understanding_seconds", "The understanding step, old interpreter and new understander",
                    ["path"], buckets=(0.5, 1, 1.5, 2, 3, 4, 5, 6, 8, 10, 15, 20, 30))  # fmt: skip
RECORD_ERRORS = Counter(P + "understanding_record_errors_total", "Turn understandings that could not be stored")


def understood(source: str, *, refused: bool, overrides: list[str], dropped: list[str], repeated: bool) -> None:
    """One turn read: its source, whether refused, the rules that corrected it, the checks that dropped a part."""
    try:
        TURNS.labels(source=source, outcome="refused" if refused else "ok").inc()
        for rule in overrides:
            OVERRIDES.labels(rule=rule).inc()
        for check in dropped:
            DROPPED.labels(check=check).inc()
        if repeated:
            REPEATED.inc()
    except Exception:  # noqa: BLE001
        log.debug("understanding not counted", exc_info=True)


def seconds(path: str, value: float) -> None:
    """The understanding step on `path` (old | new) took `value` seconds."""
    try:
        SECONDS.labels(path=path).observe(max(0.0, value))
    except Exception:  # noqa: BLE001
        log.debug("understanding latency not observed", exc_info=True)


def record_error() -> None:
    """A turn's understanding could not be stored."""
    try:
        RECORD_ERRORS.inc()
    except Exception:  # noqa: BLE001
        log.debug("understanding record error not counted", exc_info=True)


def metric_names() -> set[str]:
    """Every sample name exported here (for the rules test)."""
    counters = {c._name + "_total" for c in (TURNS, OVERRIDES, DROPPED, REPEATED, RECORD_ERRORS)}  # noqa: SLF001
    base = SECONDS._name  # noqa: SLF001
    return counters | {base + "_bucket", base + "_sum", base + "_count"}
