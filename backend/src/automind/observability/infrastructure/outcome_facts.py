"""What the turns' outcomes say over a period, for the KPI baseline (implements
`acquisition.reputation.application.baseline.OutcomeFacts`): read here because observability owns `turn_outcomes`.
A database failure becomes `ReputationStoreUnavailable` with the cause chained."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import text

from automind.acquisition.reputation.application.errors import ReputationStoreUnavailable
from automind.acquisition.reputation.domain.baseline import Satisfaction
from automind.shared.contracts.json import JsonObject
from automind.shared.infrastructure.db.errors import translate_errors
from automind.shared.infrastructure.db.session import sessionmaker

_store_errors = translate_errors(ReputationStoreUnavailable)
_SATISFACTION = text(
    "SELECT avg(score), count(*) FROM turn_outcomes WHERE created_at >= :t0 AND created_at < :t1 "
    "AND status <> 'WAITING_CONFIRMATION'"
)
_REPORT_SIGNALS = text(
    "SELECT signals FROM turn_outcomes WHERE created_at >= :t0 AND created_at < :t1 AND action = 'REPORT'"
)


class OutcomeFactsRepo:
    """Satisfaction and report signals from `turn_outcomes`."""

    @_store_errors
    async def satisfaction(self, start: datetime, end: datetime) -> Satisfaction:
        """The mean score and count of the finished turns in [start, end)."""
        async with sessionmaker()() as s:
            row = (await s.execute(_SATISFACTION, {"t0": start, "t1": end})).first()
        if row is None:
            return Satisfaction(None, 0)
        return Satisfaction(float(row[0]) if row[0] is not None else None, int(row[1]))

    @_store_errors
    async def report_signals(self, start: datetime, end: datetime) -> list[JsonObject]:
        """The outcome signals of every report in [start, end)."""
        async with sessionmaker()() as s:
            rows = (await s.execute(_REPORT_SIGNALS, {"t0": start, "t1": end})).all()
        return [r[0] or {} for r in rows]
