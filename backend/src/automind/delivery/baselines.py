"""The KPI baseline service wired (spec 011 T073): the windows and the roll-up's KPIs from the engine, the turns'
outcomes from observability. Composed here because the engine must know nothing of chats (contract
`registry-no-chat`); used by the `baseline` CLI command and the worker's `baseline` task."""

from __future__ import annotations

from typing import Any

from automind.acquisition.reputation.application.baseline import KpiBaselines
from automind.acquisition.reputation.infrastructure.baseline_store import BaselineRepo, RollupKpis, SystemClock
from automind.acquisition.worker import queue
from automind.acquisition.worker.handlers import HANDLERS, Handler, WorkerCtx
from automind.observability.infrastructure.outcome_facts import OutcomeFactsRepo


def kpi_baselines() -> KpiBaselines:
    """The baseline service over the database and the system clock."""
    return KpiBaselines(BaselineRepo(), OutcomeFactsRepo(), RollupKpis(), SystemClock())


async def baseline_task(task: queue.Task, ctx: WorkerCtx) -> dict[str, Any]:
    """The worker's daily `baseline` task: refresh the values of the open windows."""
    return {"open": await kpi_baselines().record_open()}


def worker_handlers() -> dict[str, Handler]:
    """Every task kind's handler: the engine's own and the tasks composed here."""
    return {**HANDLERS, "baseline": baseline_task}
