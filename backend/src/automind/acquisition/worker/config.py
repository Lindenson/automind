"""Worker settings from config/acquisition.yaml (`worker`, `schedule`, `prefetch`, `tasks`) over safe defaults."""

from __future__ import annotations

import copy
from typing import Any

from automind.infrastructure.config import load_yaml

DEFAULTS: dict[str, Any] = {
    "worker": {
        "concurrency": 2,
        "llm_concurrency": 2,
        "lease_s": 300,
        "poll_s": 2,
        "beat_s": 15,
        "schedule_s": 30,
        "grace_s": 20,
        "metrics_port": 9101,
    },  # fmt: skip
    "schedule": {},
    "prefetch": {"enabled": False, "eur_per_day": 0.30, "jobs_per_run": 6, "window_days": 30, "due_within_h": 48},
    # (a missing file keeps prefetch off; config/acquisition.yaml enables it)
    "tasks": {"done_days": 30, "dead_days": 90, "short_days": {}},
}


def _merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else copy.deepcopy(v)
    return out


def worker_config() -> dict[str, Any]:
    """A fresh (mutable) copy each call; a missing file gives the defaults (no schedule)."""
    try:
        data = load_yaml("acquisition.yaml")
    except FileNotFoundError:
        data = {}
    return _merge(DEFAULTS, {k: data.get(k) for k in DEFAULTS if data.get(k) is not None})
