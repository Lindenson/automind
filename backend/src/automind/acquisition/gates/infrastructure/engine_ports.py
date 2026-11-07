"""The gates' small engine ports: the journal's events (the change counter, the live overrides), the agents'
budgets, the worker's queue and the clock; and the journal's gauges the worker's heartbeat publishes."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import func, select

from automind.acquisition.agents import budget
from automind.acquisition.agents.budget import AgentBudget
from automind.acquisition.gates.domain.change import AGENT
from automind.acquisition.infrastructure import overrides
from automind.acquisition.worker import exporter, queue
from automind.shared.contracts.json import JsonObject
from automind.shared.infrastructure.db.models import OPEN_CHANGE_STATUSES, AcqChange
from automind.shared.infrastructure.db.session import sessionmaker

log = logging.getLogger(__name__)


class EngineEvents:
    """The change counter and the live overrides of this process."""

    def count(self, agent: str, status: str) -> None:
        """`automind_acq_changes_total{agent,status}`; never fails (metrics are best effort)."""
        try:
            exporter.CHANGES.labels(agent=agent, status=status).inc()
        except Exception:  # noqa: BLE001 - metrics are best effort
            log.debug("journal.count_failed", exc_info=True)

    def in_shadow(self, kind: str) -> bool:
        """A change of this object kind is in shadow."""
        return overrides.in_shadow(kind)

    async def refresh_overrides(self) -> None:
        """Reload the live overrides now."""
        await overrides.refresh(force=True)


class AgentBudgets:
    """The agents' daily budgets (`agents.budget`)."""

    def of(self, agent: str) -> AgentBudget:
        """The agent's budget."""
        return AgentBudget(agent)


class WorkerQueue:
    """The worker's task queue (`acq_tasks`)."""

    async def enqueue(self, kind: str, payload: JsonObject, *, dedupe_key: str,
                      run_at: datetime | None = None) -> str | None:  # fmt: skip
        """A task; None when one with this key exists."""
        return await queue.enqueue(kind, payload, dedupe_key=dedupe_key, run_at=run_at)


class SystemClock:
    """The system's time."""

    def now(self) -> datetime:
        """Now, timezone-aware."""
        return datetime.now(UTC)


async def publish_gauges() -> None:
    """`automind_acq_open_changes{agent,phase}` and `automind_agent_spend_today_eur{agent}`."""
    async with sessionmaker()() as s:
        q = (select(AcqChange.author, AcqChange.status, func.count())
             .where(AcqChange.status.in_(OPEN_CHANGE_STATUSES), AcqChange.closed_at.is_(None))
             .group_by(AcqChange.author, AcqChange.status))  # fmt: skip
        rows = (await s.execute(q)).all()
    caps = {a: c for a in budget.AGENTS if (c := budget.cap(a)) is not None}
    exporter.set_changes({(a.removeprefix(AGENT), st): float(n) for a, st, n in rows}, await budget.spend_by_agent(),
                         caps)  # fmt: skip
