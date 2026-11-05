"""Task handlers (contracts/task-queue.md): `HANDLERS[kind](task, ctx) -> result`, journalled in `acq_tasks.result`.

Every handler is idempotent for its dedupe key and checks its budget before it spends (`ctx.budget().charge(eur)`;
`BudgetExceeded` completes the task with `{"skipped": "budget"}`). An unknown kind is `dead` with "no handler".

The background loops of spec 010 moved here from the API process (constitution XIII): `metrics_snapshot`
(insight/metrics/snapshot.py), `registry_review` (acquisition/registry/application/review.py) and `insight_run`
(insight/loop.py). Later stories add their kinds (rollup, drift, agents, gates) to this table.
"""

from __future__ import annotations

import importlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from automind.acquisition.worker import queue
from automind.acquisition.worker.budget import BudgetGuard
from automind.infrastructure.config import load_yaml

log = logging.getLogger(__name__)


@dataclass
class WorkerCtx:
    worker_id: str
    cfg: dict[str, Any]
    task: queue.Task
    guards: list[BudgetGuard] = field(default_factory=list)

    def budget(self, cap_eur: float | None = None) -> BudgetGuard:
        """The daily budget of this task's kind (config caps, see budget.CAPS), or an explicit cap."""
        g = BudgetGuard(self.task.kind, cap_eur)
        self.guards.append(g)
        return g

    @property
    def charged(self) -> float:
        return sum(g.charged for g in self.guards)


Handler = Callable[[queue.Task, WorkerCtx], Awaitable[dict[str, Any]]]


async def metrics_snapshot(task: queue.Task, ctx: WorkerCtx) -> dict[str, Any]:
    from automind.insight.metrics import snapshot  # noqa: PLC0415

    snap = await snapshot.run_once()  # published to this process's /metrics
    return {"series": sum(len(v) for v in snap.values.values())}


async def registry_review(task: queue.Task, ctx: WorkerCtx) -> dict[str, Any]:
    from automind.acquisition.registry.application.review import review  # noqa: PLC0415

    cfg = load_yaml("registry.yaml")
    stats = await review(cfg, kind=str(task.payload.get("kind") or "daily"))
    return {"autonomy": bool(cfg.get("autonomy")), **stats}


async def insight_run(task: queue.Task, ctx: WorkerCtx) -> dict[str, Any]:
    from automind.insight.loop import run_if_due  # noqa: PLC0415

    return await run_if_due()


async def retention_snapshots(task: queue.Task, ctx: WorkerCtx) -> dict[str, Any]:
    """Snapshot retention (US1 T030): config from acquisition.yaml `snapshots` (config.snapshot_retention)."""
    from automind.acquisition.snapshots.retention import run_snapshot_retention  # noqa: PLC0415

    return dict(await run_snapshot_retention() or {})


async def prune_tasks(task: queue.Task, ctx: WorkerCtx) -> dict[str, Any]:
    t = ctx.cfg.get("tasks") or {}
    n = await queue.prune(int(t.get("done_days", 30)), int(t.get("dead_days", 90)), dict(t.get("short_days") or {}))
    return {"deleted": n}


async def prefetch(task: queue.Task, ctx: WorkerCtx) -> dict[str, Any]:
    """Slot for T057 (needs acquisition.api.acquire): off while `prefetch.enabled` is false."""
    if not (ctx.cfg.get("prefetch") or {}).get("enabled"):
        return {"skipped": "disabled"}
    try:
        mod = importlib.import_module("automind.acquisition.worker.prefetch")
    except ImportError:
        return {"skipped": "not implemented"}
    return dict(await mod.run(task, ctx))


async def reputation_signals(task: queue.Task, ctx: WorkerCtx) -> dict[str, Any]:
    """Spec 011 T070: gold, physics, agreement and replacement signals of the variants touched lately, read from the
    stored claims (no pipeline hook needed); disputed wrong signals queue a `blame_judge` task."""
    from datetime import UTC, datetime, timedelta  # noqa: PLC0415

    from automind.acquisition.reputation import rollup, signals  # noqa: PLC0415

    hours = float(task.payload.get("lookback_h") or (ctx.cfg.get("reputation") or {}).get("lookback_h", 26))
    out = await signals.scan(since=datetime.now(UTC) - timedelta(hours=hours))
    try:
        await rollup.publish_gauges()
    except Exception:  # noqa: BLE001 - gauges are best effort
        log.exception("reputation.gauges_failed")
    return out


async def rollup(task: queue.Task, ctx: WorkerCtx) -> dict[str, Any]:
    """Spec 011 T072: acq_daily, exploration reset, component fade, reputation gauges."""
    from automind.acquisition.reputation import rollup as daily  # noqa: PLC0415

    return await daily.run()


async def baseline(task: queue.Task, ctx: WorkerCtx) -> dict[str, Any]:
    """Spec 011 T073: refresh the values of open KPI baselines."""
    from automind.acquisition.reputation.baseline import record_open  # noqa: PLC0415

    return await record_open()


async def blame_judge(task: queue.Task, ctx: WorkerCtx) -> dict[str, Any]:
    """Spec 011 T071: settle one disputed signal within `agents.budgets.blame_judge`."""
    from automind.acquisition.agents.blame_judge import judge  # noqa: PLC0415

    return await judge(str(task.payload["signal_id"]), charge=ctx.budget().charge)


HANDLERS: dict[str, Handler] = {
    "metrics_snapshot": metrics_snapshot,
    "registry_review": registry_review,
    "insight_run": insight_run,
    "retention_snapshots": retention_snapshots,
    "prune_tasks": prune_tasks,
    "prefetch": prefetch,
    "reputation_signals": reputation_signals,
    "rollup": rollup,
    "baseline": baseline,
    "blame_judge": blame_judge,
}
