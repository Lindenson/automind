"""Spec 011 T054: period-scoped dedupe keys of the worker's scheduler (pure part) and the shipped schedule."""

from datetime import UTC, datetime

from automind.acquisition.worker import scheduler
from automind.acquisition.worker.config import worker_config
from automind.acquisition.worker.handlers import HANDLERS

SCHEDULE = {
    "metrics_snapshot": {"every_s": 60, "key": "snap"},
    "registry_review": {"daily": "03:00", "key": "review"},
    "prefetch": {"hourly": [6, 22], "key": "prefetch"},
    "off": {"every_s": 60, "enabled": False},
}


def _keys(at: datetime) -> dict[str, str]:
    return {d.kind: d.dedupe_key for d in scheduler.due(SCHEDULE, at)}


def test_periods_and_keys():
    assert _keys(datetime(2026, 11, 5, 2, 59, 59, tzinfo=UTC)) == {"metrics_snapshot": "snap:2026-11-05T02:59"}
    assert _keys(datetime(2026, 11, 5, 3, 0, 1, tzinfo=UTC)) == {
        "metrics_snapshot": "snap:2026-11-05T03:00", "registry_review": "review:2026-11-05"}  # fmt: skip
    k = _keys(datetime(2026, 11, 5, 6, 30, tzinfo=UTC))
    assert k["prefetch"] == "prefetch:2026-11-05T06" and "off" not in k
    assert "prefetch" not in _keys(datetime(2026, 11, 5, 23, 0, tzinfo=UTC))


def test_run_at_is_the_period_start():
    due = {d.kind: d for d in scheduler.due(SCHEDULE, datetime(2026, 11, 5, 3, 0, 42, tzinfo=UTC))}
    assert due["metrics_snapshot"].run_at == datetime(2026, 11, 5, 3, 0, tzinfo=UTC)
    assert due["registry_review"].run_at == datetime(2026, 11, 5, 3, 0, tzinfo=UTC)


def test_interval_is_the_longest_gap():
    assert scheduler.interval_s({"every_s": 60}) == 60
    assert scheduler.interval_s({"daily": "03:00"}) == 86400
    assert scheduler.interval_s({"hourly": [6, 22]}) == 8 * 3600  # 22:00 -> 06:00


def test_shipped_schedule_has_handlers_and_prefetch_runs_hourly():
    cfg = worker_config()
    assert set(cfg["schedule"]) <= set(HANDLERS)
    assert cfg["prefetch"]["enabled"] is True  # T057: the owner accepted the €0.30/day budget
    assert {"metrics_snapshot", "registry_review", "insight_run", "prune_tasks", "prefetch"} <= set(
        scheduler.enabled(cfg["schedule"])
    )
