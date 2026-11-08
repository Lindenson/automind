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
from automind.shared.infrastructure.config.loader import load_yaml

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
    from automind.observability.metrics import snapshot  # noqa: PLC0415

    snap = await snapshot.run_once()  # published to this process's /metrics
    return {"series": sum(len(v) for v in snap.values.values())}


async def registry_review(task: queue.Task, ctx: WorkerCtx) -> dict[str, Any]:
    from automind.acquisition.registry.infrastructure.wiring import daily_review  # noqa: PLC0415

    cfg = load_yaml("registry.yaml")
    stats = await daily_review(cfg).run(kind=str(task.payload.get("kind") or "daily"))
    return {"autonomy": bool(cfg.get("autonomy")), **stats}


async def insight_run(task: queue.Task, ctx: WorkerCtx) -> dict[str, Any]:
    from automind.observability.loop import run_if_due  # noqa: PLC0415

    return await run_if_due()


async def retention_snapshots(task: queue.Task, ctx: WorkerCtx) -> dict[str, Any]:
    """Snapshot retention (US1 T030): config from acquisition.yaml `snapshots` (config.snapshot_retention)."""
    from automind.acquisition.snapshots.retention import run_snapshot_retention  # noqa: PLC0415

    return dict(await run_snapshot_retention() or {})


async def prune_tasks(task: queue.Task, ctx: WorkerCtx) -> dict[str, Any]:
    t = ctx.cfg["tasks"]
    n = await queue.prune(int(t["done_days"]), int(t["dead_days"]), dict(t["short_days"]))
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

    from automind.acquisition.reputation.infrastructure.wiring import daily_rollup, signal_scan  # noqa: PLC0415

    hours = float(task.payload.get("lookback_h") or (ctx.cfg.get("reputation") or {}).get("lookback_h", 26))
    out = await signal_scan().scan(since=datetime.now(UTC) - timedelta(hours=hours))
    try:
        await daily_rollup().publish_gauges()
    except Exception:  # noqa: BLE001 - gauges are best effort
        log.exception("reputation.gauges_failed")
    return out


async def rollup(task: queue.Task, ctx: WorkerCtx) -> dict[str, Any]:
    """Spec 011 T072: acq_daily, exploration reset, component fade, reputation gauges."""
    from automind.acquisition.reputation.infrastructure.wiring import daily_rollup  # noqa: PLC0415

    return await daily_rollup().run()


async def blame_judge(task: queue.Task, ctx: WorkerCtx) -> dict[str, Any]:
    """Spec 011 T071: settle one disputed signal within `agents.budgets.blame_judge`."""
    from automind.acquisition.agents.blame_judge import judge  # noqa: PLC0415

    return await judge(str(task.payload["signal_id"]), charge=ctx.budget().charge)


async def scout(task: queue.Task, ctx: WorkerCtx) -> dict[str, Any]:
    """Spec 011 T108: new sources for gaps within `agents.budgets.scout` and `registry.discovery.eur_per_day`, at
    most `agents.max_runs_per_day.scout` runs a day; changes only registry rows (journalled, hard limits)."""
    from automind.acquisition.agents import scout as agent  # noqa: PLC0415
    from automind.acquisition.infrastructure.wiring import live_search  # noqa: PLC0415

    max_runs = int(load_yaml("agents.yaml")["max_runs_per_day"]["scout"])
    if await agent.runs_today() >= max_runs:
        return {"skipped": "runs"}
    return await agent.run(live_search(), charge=ctx.budget().charge, used=await agent.used_today(), task_id=task.id)


def _day(task: queue.Task) -> Any:
    """The task's `day` (ISO) or yesterday (UTC): a daily task rolls up the day that has ended."""
    from datetime import UTC, date, datetime, timedelta  # noqa: PLC0415

    if d := task.payload.get("day"):
        return date.fromisoformat(str(d))
    return datetime.now(UTC).date() - timedelta(days=1)


async def parser_daily(task: queue.Task, ctx: WorkerCtx) -> dict[str, Any]:
    """Spec 011 T089: per parser version and day, fields per page, pass rate and structure fingerprint."""
    from automind.acquisition.drift import daily  # noqa: PLC0415

    out = await daily.roll_day(_day(task))
    try:
        await daily.publish_gauges()
    except Exception:  # noqa: BLE001 - gauges are best effort
        log.exception("parser.gauges_failed")
    return out


async def drift(task: queue.Task, ctx: WorkerCtx) -> dict[str, Any]:
    """Spec 011 T089: the drift detectors on each running parser version (degrade, journal, parser doctor), after
    the day's roll-up (idempotent, so the order of the two daily tasks does not matter)."""
    from automind.acquisition.drift import daily  # noqa: PLC0415

    day = _day(task)
    rolled = await daily.roll_day(day)
    return {**await daily.detect(day), "rolled": rolled["rows"]}


def _guard(task: queue.Task, ctx: WorkerCtx) -> Any:
    """The daily budget of the agent whose change (or run) this task is (agents/budget.py)."""
    from automind.acquisition.agents.budget import AgentBudget  # noqa: PLC0415

    g = AgentBudget(str(task.payload.get("agent") or task.kind))
    ctx.guards.append(g)
    return g


async def gate_replay(task: queue.Task, ctx: WorkerCtx) -> dict[str, Any]:
    """Spec 011 T101: the replay gate of one change."""
    from automind.acquisition.gates.infrastructure.wiring import replay_gate  # noqa: PLC0415

    return await replay_gate().run(str(task.payload["change_id"]), budget=_guard(task, ctx))


async def gate_shadow(task: queue.Task, ctx: WorkerCtx) -> dict[str, Any]:
    """Spec 011 T102: one live page added to a change's shadow, then the shadow decision."""
    from automind.acquisition.gates.infrastructure.wiring import shadow_gate  # noqa: PLC0415

    sid = task.payload.get("snapshot_id")
    return await shadow_gate().run(str(task.payload["change_id"]), str(sid) if sid else None,
                                   budget=_guard(task, ctx))  # fmt: skip


async def watch(task: queue.Task, ctx: WorkerCtx) -> dict[str, Any]:
    """Spec 011 T103: the watch of one accepted change (keep or roll back)."""
    from automind.acquisition.gates.infrastructure.wiring import watch as watching  # noqa: PLC0415

    return await watching().check(str(task.payload["change_id"]))


async def evaluator(task: queue.Task, ctx: WorkerCtx) -> dict[str, Any]:
    """Spec 011 T103: daily, code only — accuracy KPI, shadow deadlines, watch and rollbacks, gauges."""
    from automind.acquisition.agents import evaluator as ev  # noqa: PLC0415

    return await ev.run()


async def parser_doctor(task: queue.Task, ctx: WorkerCtx) -> dict[str, Any]:
    """Spec 011 T105: a new parser spec version for a drifted parser (or a spec site without one)."""
    from automind.acquisition.agents import parser_doctor as doctor  # noqa: PLC0415

    return await doctor.handle(dict(task.payload), guard=_guard(task, ctx))


async def rule_auditor(task: queue.Task, ctx: WorkerCtx) -> dict[str, Any]:
    """Spec 011 T106: a bounded keyword or threshold change for rules that reject confirmed values."""
    from automind.acquisition.agents import rule_auditor as auditor  # noqa: PLC0415

    return await auditor.handle(dict(task.payload), guard=_guard(task, ctx))


async def extractor_tuner(task: queue.Task, ctx: WorkerCtx) -> dict[str, Any]:
    """Spec 011 T107: an extraction prompt version or extractor model when accuracy or yield falls."""
    from automind.acquisition.agents import extractor_tuner as tuner  # noqa: PLC0415

    return await tuner.handle(dict(task.payload), guard=_guard(task, ctx))


# Kinds enqueued before their handler exists: the worker leaves them queued instead of burying them as "no
# handler" (the scout arrives on its own branch, spec 011 T108).
AWAITING_HANDLER: tuple[str, ...] = ()

HANDLERS: dict[str, Handler] = {
    "metrics_snapshot": metrics_snapshot,
    "registry_review": registry_review,
    "insight_run": insight_run,
    "retention_snapshots": retention_snapshots,
    "prune_tasks": prune_tasks,
    "prefetch": prefetch,
    "reputation_signals": reputation_signals,
    "rollup": rollup,
    "blame_judge": blame_judge,
    "parser_daily": parser_daily,
    "drift": drift,
    "scout": scout,
    "gate_replay": gate_replay,
    "gate_shadow": gate_shadow,
    "watch": watch,
    "evaluator": evaluator,
    "parser_doctor": parser_doctor,
    "rule_auditor": rule_auditor,
    "extractor_tuner": extractor_tuner,
}
