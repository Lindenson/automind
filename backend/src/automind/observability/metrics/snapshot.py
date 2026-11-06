"""The slow Prometheus values (spec 010 US9, FR-031): computed from the journals every minute, served from memory.

Missing tables or empty data give empty series, never an error: the snapshot runs from the first release on.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import text

from automind.shared.infrastructure.config.settings import settings
from automind.shared.infrastructure.db.session import sessionmaker
from automind.shared.infrastructure.metrics import prom

log = logging.getLogger(__name__)

EVERY_S = 60  # the worker runs `metrics_snapshot` this often (config/acquisition.yaml schedule)
WINDOWS = {"7d": 7, "30d": 30}
COMPLAINT_KINDS = ("wrong_value", "bad_source", "complaint", "rephrase", "correction")


async def _rows(sql: str, **params: Any) -> list[Any]:
    async with sessionmaker()() as s:
        return list((await s.execute(text(sql), params)).all())


async def _satisfaction(snap: prom.Snapshot, now: datetime) -> None:
    for w, days in WINDOWS.items():
        since = now - timedelta(days=days)
        rows = await _rows(
            "SELECT coalesce(request_kind,'unknown'), avg(score), count(*) FROM turn_outcomes "
            "WHERE created_at >= :since AND status <> 'WAITING_CONFIRMATION' GROUP BY 1",
            since=since,
        )
        total_n, total_sum = 0, 0.0
        for kind, avg, n in rows:
            snap.set("satisfaction_index", (kind, w), float(avg or 0))
            snap.set("satisfaction_turns", (kind, w), int(n))
            total_n += int(n)
            total_sum += float(avg or 0) * int(n)
        if total_n:
            snap.set("satisfaction_index", ("all", w), total_sum / total_n)
            snap.set("satisfaction_turns", ("all", w), total_n)
        for dim in ("language", "persona"):
            for key, avg, _n in await _rows(
                f"SELECT coalesce({dim},'unknown'), avg(score), count(*) FROM turn_outcomes "  # noqa: S608 - fixed names
                "WHERE created_at >= :since AND status <> 'WAITING_CONFIRMATION' GROUP BY 1",
                since=since,
            ):
                snap.set("satisfaction_index_by", (dim, key, w), float(avg or 0))


async def _nodata(snap: prom.Snapshot, now: datetime) -> None:
    for w, days in WINDOWS.items():
        rows = await _rows(
            "SELECT signals FROM turn_outcomes WHERE created_at >= :since AND action = 'REPORT'",
            since=now - timedelta(days=days),
        )
        if not rows:
            continue
        per_area: dict[str, int] = defaultdict(int)
        for (sig,) in rows:
            for area in {i.get("area") for i in (sig or {}).get("nodata_items") or [] if i.get("area")}:
                per_area[area] += 1
        for area, n in per_area.items():
            snap.set("nodata_share", (area, w), n / len(rows))


async def _feedback(snap: prom.Snapshot, now: datetime) -> None:
    day = {
        k: n
        for k, n in await _rows(
            "SELECT kind, count(*) FROM feedback WHERE created_at >= :since GROUP BY 1", since=now - timedelta(days=1)
        )
    }
    month = {
        k: n
        for k, n in await _rows(
            "SELECT kind, count(*) FROM feedback WHERE created_at >= :since GROUP BY 1", since=now - timedelta(days=30)
        )
    }
    for kind in COMPLAINT_KINDS:
        snap.set("complaints_24h", (kind,), int(day.get(kind, 0)))
        snap.set("complaints_daily_avg_30d", (kind,), int(month.get(kind, 0)) / 30)


async def _accuracy(snap: prom.Snapshot, now: datetime) -> None:
    for w, days in WINDOWS.items():
        for area, right, total in await _rows(
            "SELECT c.area, sum(CASE WHEN t.verdict='right' THEN t.weight ELSE 0 END), sum(t.weight) "
            "FROM truth_signals t JOIN capabilities c ON c.id = t.capability_id "
            "WHERE t.created_at >= :since AND t.blame = 'source' GROUP BY 1",
            since=now - timedelta(days=days),
        ):
            if total:
                snap.set("accuracy_share", (area, w), float(right or 0) / float(total))
                snap.set("accuracy_signals", (area, w), float(total))
    for domain, n in await _rows(
        "SELECT c.domain, count(*) FROM truth_signals t JOIN capabilities c ON c.id = t.capability_id "
        "WHERE t.created_at >= :since AND t.verdict = 'wrong' GROUP BY 1",
        since=now - timedelta(days=1),
    ):
        snap.set("source_wrong_values_24h", (domain,), int(n))


async def _registry(snap: prom.Snapshot) -> None:
    for area, status, n in await _rows("SELECT area, status, count(*) FROM capabilities GROUP BY 1, 2"):
        snap.set("capabilities", (area, status), int(n))
    for area, market, n in await _rows(
        "SELECT area, market, count(*) FROM capabilities WHERE status = 'active' GROUP BY 1, 2"
    ):
        snap.set("active_sources", (area, market), int(n))
    for domain, area, market, score, lb, yld in await _rows(
        "SELECT domain, area, market, score, acc_lb, yield_ FROM capabilities "
        "WHERE status IN ('candidate','active','degraded')"
    ):
        snap.set("source_score", (domain, area, market), float(score))
        snap.set("source_accuracy_lb", (domain, area, market), float(lb))
        snap.set("source_yield", (domain, area, market), float(yld))


async def _models(snap: prom.Snapshot, now: datetime) -> None:
    for w, since in (("1h", now - timedelta(hours=1)), ("7d", now - timedelta(days=7))):
        for role, fb, n in await _rows(
            "SELECT role, sum(CASE WHEN fallback THEN 1 ELSE 0 END), count(*) FROM llm_calls "
            "WHERE created_at >= :since GROUP BY 1",
            since=since,
        ):
            if n:
                snap.set("llm_fallback_share", (role, w), float(fb or 0) / int(n))
    from automind.shared.infrastructure.llm import gateway as llm_gateway  # noqa: PLC0415

    mono = time.monotonic()
    per_provider: dict[str, float] = defaultdict(float)
    for name, until in dict(llm_gateway._EXHAUSTED).items():  # noqa: SLF001 - read-only view of the quota state
        per_provider[name.split(":", 1)[0]] = max(per_provider[name.split(":", 1)[0]], max(0.0, until - mono))
    for provider, secs in per_provider.items():
        snap.set("provider_unavailable_seconds", (provider,), secs)


async def _spend(snap: prom.Snapshot) -> None:
    from automind.chat.infrastructure.persistence.repositories import TurnRepo  # noqa: PLC0415
    from automind.shared.infrastructure.config.loader import load_yaml  # noqa: PLC0415

    snap.set("spend_today_eur", (), await TurnRepo().spent_today())
    snap.set("daily_cap_eur", (), float(settings().daily_cap_eur or 0))
    start = datetime.now(ZoneInfo("Europe/Madrid")).replace(hour=0, minute=0, second=0, microsecond=0)
    budgets = {
        "insight": float(load_yaml("insight.yaml").get("budget_eur", 0)),
        "registry": float((load_yaml("registry.yaml").get("discovery") or {}).get("eur_per_day", 0)),
    }
    for loop, table in (("insight", "insight_runs"), ("registry", "registry_runs")):
        (spent,) = (
            await _rows(
                f"SELECT coalesce(sum(cost_eur),0) FROM {table} WHERE started_at >= :s",  # noqa: S608
                s=start,
            )
        )[0]
        snap.set("background_spend_today_eur", (loop,), float(spent or 0))
        snap.set("background_budget_eur", (loop,), budgets[loop])


async def _issues(snap: prom.Snapshot) -> None:
    for comp, status, n in await _rows("SELECT component, status, count(*) FROM insight_issues GROUP BY 1, 2"):
        snap.set("issues", (comp, status), int(n))


async def _engine(snap: prom.Snapshot) -> None:
    """Spec 011 T031: snapshot store size, gold values per dataset, claims that do not name their producer."""
    for (n,) in await _rows("SELECT coalesce(sum(stored_bytes), 0) FROM snapshot_blobs"):
        snap.set("snapshot_store_bytes", (), float(n or 0))
    for dataset, n in await _rows("SELECT coalesce(dataset_id, origin), count(*) FROM gold_values GROUP BY 1"):
        snap.set("gold_values", (dataset,), int(n))
    for (n,) in await _rows("SELECT count(*) FROM claims WHERE producer_version IS NULL"):
        snap.set("claims_without_producer", (), int(n))


async def _readers(snap: prom.Snapshot) -> None:
    """Zero streaks of the running parser versions (spec 011 US4: kept in parser_versions, so every process's
    pages count), and this process's own count for readers not stored yet (the YAML fallback)."""
    from automind.acquisition.parsing.registry import STREAKS  # noqa: PLC0415

    streaks = dict(STREAKS)
    for reader, n in await _rows(
        "SELECT reader, zero_streak FROM parser_versions WHERE status IN ('active', 'degraded')"
    ):
        streaks[str(reader)] = max(int(n), streaks.get(str(reader), 0))
    for reader, n in sorted(streaks.items()):
        snap.set("reader_zero_streak", (reader,), n)


async def refresh() -> prom.Snapshot:
    snap = prom.Snapshot()
    now = datetime.now(UTC)
    parts = (
        _satisfaction(snap, now),
        _nodata(snap, now),
        _feedback(snap, now),
        _accuracy(snap, now),
        _registry(snap),
        _models(snap, now),
        _spend(snap),
        _issues(snap),
        _engine(snap),
        _readers(snap),
    )
    for part in parts:
        try:
            await part
        except Exception:  # noqa: BLE001 - one failing query leaves its series empty, never the whole snapshot
            log.exception("metrics.snapshot_part_failed")
    return snap


async def run_once() -> prom.Snapshot:
    snap = await refresh()
    prom.publish(snap)
    return snap
