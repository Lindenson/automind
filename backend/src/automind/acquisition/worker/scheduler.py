"""Periodic tasks without a second table (research R6): every `schedule_s` the scheduler works out which periods of
config/acquisition.yaml `schedule` are due now and enqueues them with a period-scoped dedupe key
(`snap:2026-11-05T03:00`, `review:2026-11-05`, `prefetch:2026-11-05T06`); `INSERT … ON CONFLICT DO NOTHING` makes
each period run once, whatever the number of workers.

`due()` and `interval_s()` are pure; `tick()` writes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any


@dataclass(frozen=True)
class Due:
    kind: str
    dedupe_key: str
    run_at: datetime
    priority: int = 5


def enabled(schedule: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {k: dict(e or {}) for k, e in (schedule or {}).items() if (e or {}).get("enabled", True)}


def _hm(s: str) -> tuple[int, int]:
    h, m = str(s).split(":")
    return int(h), int(m)


def due(schedule: dict[str, Any], now: datetime) -> list[Due]:
    """The current period of every enabled entry whose start has passed (UTC)."""
    now = now.astimezone(UTC)
    out: list[Due] = []
    for kind, e in enabled(schedule).items():
        key, prio = str(e.get("key") or kind), int(e.get("priority", 5))
        if "every_s" in e:
            every = max(1, int(e["every_s"]))
            start = datetime.fromtimestamp(int(now.timestamp()) // every * every, UTC)
            out.append(Due(kind, f"{key}:{start:%Y-%m-%dT%H:%M}", start, prio))
        elif "daily" in e:
            h, m = _hm(e["daily"])
            at = now.replace(hour=h, minute=m, second=0, microsecond=0)
            if now >= at:
                out.append(Due(kind, f"{key}:{now:%Y-%m-%d}", at, prio))
        elif "hourly" in e:
            first, last = (int(x) for x in e["hourly"])
            if first <= now.hour <= last:
                at = now.replace(minute=0, second=0, microsecond=0)
                out.append(Due(kind, f"{key}:{now:%Y-%m-%dT%H}", at, prio))
    return out


def interval_s(entry: dict[str, Any]) -> float:
    """The longest expected gap between two runs of an entry (for the loop-stale alert)."""
    if "every_s" in entry:
        return float(entry["every_s"])
    if "hourly" in entry:
        first, last = (int(x) for x in entry["hourly"])
        return float(max(3600, (24 - (last - first)) * 3600))
    return float(timedelta(days=1).total_seconds())


async def tick(schedule: dict[str, Any], now: datetime | None = None) -> list[str]:
    """Enqueue the due periods; returns the kinds newly enqueued."""
    from automind.acquisition.worker import queue  # noqa: PLC0415

    added = []
    for d in due(schedule, now or datetime.now(UTC)):
        if await queue.enqueue(d.kind, {}, dedupe_key=d.dedupe_key, run_at=d.run_at, priority=d.priority):
            added.append(d.kind)
    return added
