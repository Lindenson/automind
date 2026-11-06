"""Daily budgets and run limits of the engine's agents (spec 011 US5 AS-4, research R13; contracts/task-queue.md).

An agent's spend today (UTC) = the `cost_eur` of its own tasks and of the gate tasks that run its changes
(`gate_replay`, `gate_shadow`, `watch` with `payload.agent`), finished today, plus the model spend of those still
running. Budgets and `max_runs_per_day` come from config/agents.yaml — read, never written (human-set only).
When either is used up the agent stops until the next day.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text

from automind.acquisition.infrastructure.config import agents_config
from automind.acquisition.worker.budget import BudgetGuard
from automind.shared.infrastructure.db.session import sessionmaker

AGENTS = ("scout", "parser_doctor", "rule_auditor", "extractor_tuner", "blame_judge")
GATE_KINDS = ("gate_replay", "gate_shadow", "watch")

_SPENT = text(
    """
    SELECT coalesce((SELECT sum(cost_eur) FROM acq_tasks
                     WHERE (kind = :a OR (kind = ANY(:g) AND payload->>'agent' = :a))
                       AND state = 'done' AND finished_at >= :day), 0)
         + coalesce((SELECT sum(l.cost_eur) FROM llm_calls l JOIN acq_tasks t ON t.id = l.job_id
                     WHERE (t.kind = :a OR (t.kind = ANY(:g) AND t.payload->>'agent' = :a))
                       AND t.state = 'running' AND l.created_at >= :day), 0)
    """
)
_RUNS = text(
    "SELECT count(*) FROM acq_tasks WHERE kind = :a AND state = 'done' AND finished_at >= :day "
    "AND coalesce(result->>'skipped', '') = ''"
)


def _today() -> datetime:
    return datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


def _cfg(section: str, agent: str) -> Any:
    try:
        return (agents_config().get(section) or {}).get(agent)
    except FileNotFoundError:
        return None


def cap(agent: str) -> float | None:
    v = _cfg("budgets", agent)
    return float(v) if isinstance(v, int | float) else None


def max_runs(agent: str) -> int | None:
    v = _cfg("max_runs_per_day", agent)
    return int(v) if isinstance(v, int) else None


async def spent_today(agent: str) -> float:
    async with sessionmaker()() as s:
        got = await s.execute(_SPENT, {"a": agent, "g": list(GATE_KINDS), "day": _today()})
        return float(got.scalar() or 0)


async def runs_today(agent: str) -> int:
    async with sessionmaker()() as s:
        return int((await s.execute(_RUNS, {"a": agent, "day": _today()})).scalar() or 0)


class AgentBudget(BudgetGuard):
    """`charge(eur)` raises `BudgetExceeded` past the agent's daily budget (its tasks and its gate tasks)."""

    def __init__(self, agent: str, cap_eur: float | None = None) -> None:
        super().__init__(agent, cap_eur if cap_eur is not None else cap(agent))
        self.agent = agent

    async def spent(self) -> float:
        return await spent_today(self.agent)


async def stop_reason(agent: str) -> str | None:
    """Why the agent may not start another run today ("budget", "max_runs"), or None."""
    c = cap(agent)
    if c is not None and await spent_today(agent) >= c - 1e-9:
        return "budget"
    m = max_runs(agent)
    if m is not None and await runs_today(agent) >= m:
        return "max_runs"
    return None


async def spend_by_agent() -> dict[str, float]:
    """Today's spend of every agent (gauge `automind_agent_spend_today_eur`)."""
    return {a: await spent_today(a) for a in AGENTS}
