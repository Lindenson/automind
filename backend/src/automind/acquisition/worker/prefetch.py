"""The prefetch task (spec 011 T057, constitution XIII): refresh what users ask most, before they ask, in the worker.

Popular cars are the variants of `research_jobs` of the last `prefetch.window_days`, ordered by distinct chats and
then jobs; per car its areas in the order the chats asked them. An area is due when it never ran, when its freshness
(`Settings.freshness_days`, `other_fresh_days` for areas without one) ends within `due_within_h`, or when it was left
short (minimum not met) more than `short_retry_h` ago. A car with a chat's research job in flight is skipped (the
turn researches it already). Each due (car, area) is one `acquire(Need.REFRESH)` — STANDARD semantics (cache-first,
research what is missing or stale), background budget, no emit — run one after another, at most `variants_per_run`
cars and `jobs_per_run` jobs per run.

Spend: the daily cap `prefetch.eur_per_day` counts every prefetch task of the day (`acq_tasks.cost_eur` = its model
calls in `llm_calls` + its searches in `search_calls`, both carrying the task id as `job_id`). Before a job the run
stops when less than `min_eur_per_job` is left; during a job a per-job `TurnBudget` whose cost cap is what is left
refuses the next search or model call, so a run overshoots by at most one model call. The result (journalled in
`acq_tasks.result`) has the counts per area, the cars refreshed and the spend; the worker exports
`automind_prefetch_variants_total`, `automind_prefetch_areas_total{area}` and `automind_prefetch_spend_today_eur`.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import text

from automind.acquisition import api as acquisition
from automind.acquisition.worker import exporter, queue
from automind.application.usage import BudgetExceeded, Limits, TurnBudget, current_budget
from automind.config import settings
from automind.infrastructure.db.session import sessionmaker
from automind.infrastructure.llm_gateway import prices as llm_prices

if TYPE_CHECKING:
    from automind.acquisition.worker.handlers import WorkerCtx

log = logging.getLogger(__name__)

_POPULAR = text(
    """
    SELECT variant_id, count(DISTINCT chat_id) AS chats, count(*) AS jobs
    FROM research_jobs
    WHERE coalesce(started_at, finished_at) >= :since
    GROUP BY variant_id
    HAVING NOT bool_or(status = 'RUNNING' AND finished_at IS NULL AND started_at >= :busy)
    ORDER BY chats DESC, jobs DESC, variant_id
    """
)
_AREAS = text(
    """
    SELECT area, count(DISTINCT chat_id) AS chats, count(*) AS jobs
    FROM research_jobs
    WHERE variant_id = :v AND coalesce(started_at, finished_at) >= :since
    GROUP BY area
    ORDER BY chats DESC, jobs DESC, area
    """
)
_RUNS = text("SELECT area, completed_at, minimum_met FROM research_runs WHERE variant_id = :v")
_LLM = text("SELECT coalesce(sum(cost_eur), 0) FROM llm_calls WHERE job_id = :i")


def options(cfg: dict[str, Any] | None) -> dict[str, Any]:
    """The `prefetch` block of config/acquisition.yaml (the only source of its values; a missing key fails)."""
    from automind.acquisition.worker.config import worker_config  # noqa: PLC0415

    return dict(cfg) if cfg else worker_config()["prefetch"]


def fresh_days(area: str, o: dict[str, Any]) -> float:
    try:
        return float(settings().freshness_days(area))
    except KeyError:
        return float(o["other_fresh_days"])


def is_due(area: str, run: tuple[datetime, bool | None] | None, now: datetime, o: dict[str, Any]) -> bool:
    """Never ran, freshness ends within `due_within_h`, or left short more than `short_retry_h` ago."""
    if run is None:
        return True
    completed, met = run
    if completed + timedelta(days=fresh_days(area, o)) <= now + timedelta(hours=float(o["due_within_h"])):
        return True
    return met is False and completed <= now - timedelta(hours=float(o["short_retry_h"]))


async def plan(cfg: dict[str, Any] | None, now: datetime | None = None) -> list[tuple[str, str]]:
    """The (variant, area) pairs this run refreshes, most popular first, within the per-run limits."""
    o = options(cfg)
    now = now or datetime.now(UTC)
    since = now - timedelta(days=float(o["window_days"]))
    busy = now - timedelta(minutes=float(o["busy_min"]))
    out: list[tuple[str, str]] = []
    cars = 0
    async with sessionmaker()() as s:
        popular = (await s.execute(_POPULAR, {"since": since, "busy": busy})).all()
        for vid, _chats, _jobs in popular:
            if cars >= int(o["variants_per_run"]) or len(out) >= int(o["jobs_per_run"]):
                break
            runs = {r.area: (r.completed_at, r.minimum_met) for r in (await s.execute(_RUNS, {"v": vid})).all()}
            areas = [a for a, *_ in (await s.execute(_AREAS, {"v": vid, "since": since})).all()]
            due = [a for a in areas if is_due(a, runs.get(a), now, o)]
            if not due:
                continue
            cars += 1
            out += [(vid, a) for a in due][: int(o["jobs_per_run"]) - len(out)]
    return out


async def _llm_spent(task_id: str) -> float:
    async with sessionmaker()() as s:
        return float((await s.execute(_LLM, {"i": task_id})).scalar() or 0)


async def run(task: queue.Task, ctx: WorkerCtx, *, ports: Any = None) -> dict[str, Any]:
    """The `prefetch` handler (the worker checks `prefetch.enabled` first). `ports`: the engine's (tests)."""
    o = options(ctx.cfg.get("prefetch"))
    guard = ctx.budget(float(o["eur_per_day"]))
    prices = llm_prices()
    spent = 0.0  # this task's spend (model calls and searches), counted in-process
    by_area: dict[str, dict[str, int]] = {}
    refreshed: list[dict[str, Any]] = []
    cars: set[str] = set()
    stopped: str | None = None

    async def sync() -> float:
        """The guard carries what the tables do not show yet (searches; model calls are in llm_calls)."""
        guard.charged = max(0.0, spent - await _llm_spent(task.id))
        return await guard.remaining()

    todo = await plan(o)
    for vid, area in todo:
        left = await sync()
        if left <= 0 or left < float(o["min_eur_per_job"]):
            stopped = "budget"
            break
        budget = TurnBudget(None, None, prices, Limits(max_llm_calls=10_000, hard_cap_eur=left, daily_cap_eur=0.0))
        token = current_budget.set(budget)
        req = acquisition.AcquireRequest(job_id=task.id, variant_id=vid, kinds=[area], need=acquisition.Need.REFRESH)
        try:
            res = await acquisition.acquire(req, None, ports=ports)
        except BudgetExceeded:
            stopped = "budget"
            break
        finally:
            spent += budget.cost_eur
            current_budget.reset(token)
        (k,) = res.kinds
        a = by_area.setdefault(area, {"jobs": 0, "ok": 0, "accepted": 0, "rejected": 0, "docs": 0})
        a["jobs"] += 1
        a["ok"] += int(k.ok)
        a["accepted"] += k.accepted
        a["rejected"] += k.rejected
        a["docs"] += k.docs
        refreshed.append({"variant_id": vid, "area": area, "accepted": k.accepted, "minimum_met": k.minimum_met})
        if vid not in cars:
            cars.add(vid)
            exporter.PREFETCH_VARIANTS.inc()
        exporter.PREFETCH_AREAS.labels(area=area).inc()
        log.info("prefetch.refreshed variant=%s area=%s ok=%s accepted=%s", vid, area, k.ok, k.accepted)
    left = await sync()
    today = await guard.spent() + guard.charged  # every prefetch task of the day, this one included
    exporter.PREFETCH_SPEND.set(today)
    exporter.PREFETCH_BUDGET.set(float(o["eur_per_day"]))
    out = {"planned": len(todo), "jobs": len(refreshed), "variants": len(cars), "by_area": by_area,
           "refreshed": refreshed, "stopped": stopped, "spent_eur": round(spent, 6),
           "spent_today_eur": round(today, 6), "remaining_eur": round(left, 6)}  # fmt: skip
    log.info("prefetch.done %s", {k: v for k, v in out.items() if k != "refreshed"})
    return out
