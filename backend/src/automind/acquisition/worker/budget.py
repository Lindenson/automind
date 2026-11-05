"""Daily budgets of background task kinds (contracts/task-queue.md): a handler checks before it spends.

Spent today (UTC) = `cost_eur` of the kind's tasks finished today + model spend (`llm_calls.job_id` = task id) of
its tasks still running. `charge()` raises `BudgetExceeded`; the worker then completes the task with
`{"skipped": "budget"}`.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import text

from automind.infrastructure.config import load_yaml
from automind.infrastructure.db.session import sessionmaker


class BudgetExceeded(RuntimeError):  # noqa: N818 - the contract's name
    """The kind's daily background budget would be exceeded."""


# kind -> (config file, dotted path of its daily cap)
CAPS: dict[str, tuple[str, str]] = {
    "prefetch": ("acquisition.yaml", "prefetch.eur_per_day"),
    "registry_review": ("registry.yaml", "discovery.eur_per_day"),
    "insight_run": ("insight.yaml", "budget_eur"),
    "blame_judge": ("agents.yaml", "budgets.blame_judge"),
}

_SPENT = text(
    """
    SELECT coalesce((SELECT sum(cost_eur) FROM acq_tasks
                     WHERE kind = :k AND state = 'done' AND finished_at >= :day), 0)
         + coalesce((SELECT sum(l.cost_eur) FROM llm_calls l JOIN acq_tasks t ON t.id = l.job_id
                     WHERE t.kind = :k AND t.state = 'running' AND l.created_at >= :day), 0)
    """
)


def cap_for(kind: str) -> float | None:
    if kind not in CAPS:
        return None
    file, path = CAPS[kind]
    try:
        node: object = load_yaml(file)
    except FileNotFoundError:
        return None
    for part in path.split("."):
        node = node.get(part) if isinstance(node, dict) else None
    return float(node) if isinstance(node, int | float) else None


class BudgetGuard:
    def __init__(self, kind: str, cap_eur: float | None = None) -> None:
        self.kind = kind
        self.cap = cap_eur if cap_eur is not None else cap_for(kind)
        self.charged = 0.0  # spend charged by this guard that is not in the tables yet

    async def spent(self) -> float:
        day = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        async with sessionmaker()() as s:
            return float((await s.execute(_SPENT, {"k": self.kind, "day": day})).scalar() or 0)

    async def remaining(self) -> float:
        if self.cap is None:
            return float("inf")
        return max(0.0, self.cap - await self.spent() - self.charged)

    async def charge(self, eur: float) -> None:
        if eur > await self.remaining() + 1e-9:
            raise BudgetExceeded(f"{self.kind}: {eur:.4f} EUR over today's budget {self.cap}")
        self.charged += eur
