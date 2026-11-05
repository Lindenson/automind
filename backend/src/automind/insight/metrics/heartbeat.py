"""Health of the background loops (spec 010 FR-033): kept in memory, exported to Prometheus.

A loop that stops silently is caught by the shipped rule `AutomindLoopStale`, which compares the last success time
with the expected interval.
"""

from __future__ import annotations

import time

_STATE: dict[str, dict[str, float]] = {}


def register(loop: str, interval_s: float) -> None:
    st = _STATE.setdefault(loop, {"last_ok": 0.0, "fails": 0.0, "interval": float(interval_s)})
    st["interval"] = float(interval_s)
    if not st["last_ok"]:
        st["last_ok"] = time.time()  # a fresh start counts as healthy until the first interval has passed


def beat(loop: str, ok: bool, interval_s: float | None = None) -> None:
    st = _STATE.setdefault(loop, {"last_ok": 0.0, "fails": 0.0, "interval": float(interval_s or 0)})
    if interval_s is not None:
        st["interval"] = float(interval_s)
    if ok:
        st["last_ok"] = time.time()
        st["fails"] = 0.0
    else:
        st["fails"] += 1


def state() -> dict[str, dict[str, float]]:
    return {k: dict(v) for k, v in _STATE.items()}


def samples() -> dict[str, list[tuple[tuple[str, ...], float]]]:
    out: dict[str, list[tuple[tuple[str, ...], float]]] = {
        "loop_last_success_timestamp_seconds": [],
        "loop_fails_in_row": [],
        "loop_interval_seconds": [],
    }
    for loop, st in sorted(_STATE.items()):
        out["loop_last_success_timestamp_seconds"].append(((loop,), st["last_ok"]))
        out["loop_fails_in_row"].append(((loop,), st["fails"]))
        out["loop_interval_seconds"].append(((loop,), st["interval"]))
    return out
