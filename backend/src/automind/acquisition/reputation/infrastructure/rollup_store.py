"""The roll-up's store over the database (spec 011 T072): the day's counts from `registry_attempts`, `search_calls`
and `truth_signals`, the `acq_daily` rows, the areas' sums, and today's exploration spend reset; plus the worker's
gauges and the calendar. A database failure becomes `ReputationStoreUnavailable`."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import text, update
from sqlalchemy.dialects.postgresql import insert

from automind.acquisition.reputation.application.errors import ReputationStoreUnavailable
from automind.acquisition.reputation.application.rollup import DayCounts
from automind.acquisition.reputation.domain.rollup import (
    ANY_MARKET,
    AreaTotals,
    AttemptCounts,
    DailyValues,
    SearchCounts,
    SignalCounts,
)
from automind.acquisition.worker import exporter
from automind.shared.infrastructure.db.errors import translate_errors
from automind.shared.infrastructure.db.models import AcqDaily, CapabilityRow
from automind.shared.infrastructure.db.session import sessionmaker

AREA_CHARS, MARKET_CHARS = 20, 8  # the columns of `acq_daily`
_store_errors = translate_errors(ReputationStoreUnavailable)
_ATTEMPTS = text(
    """
    SELECT c.area, c.market, count(*), coalesce(sum(CASE WHEN a.outcome = 'accepted' THEN a.values ELSE 0 END), 0),
           coalesce(sum(a.searches), 0), coalesce(sum(a.cost_eur), 0),
           coalesce(sum(CASE WHEN c.status = 'candidate' THEN a.cost_eur ELSE 0 END), 0)
    FROM registry_attempts a JOIN capabilities c ON c.id = a.capability_id
    WHERE a.created_at >= :t0 AND a.created_at < :t1 GROUP BY 1, 2
    """
)
_SEARCHES = text(
    """
    SELECT coalesce(area, 'unknown'), count(*), coalesce(sum(cost_eur), 0) FROM search_calls
    WHERE created_at >= :t0 AND created_at < :t1 AND kind = 'search' AND NOT cached GROUP BY 1
    """
)
_SIGNALS = text(
    """
    SELECT coalesce(t.details->>'area', 'unknown'), coalesce(c.market, :any),
           count(DISTINCT CASE WHEN t.verdict = 'wrong' THEN coalesce(t.claim_id, t.id) END),
           count(*) FILTER (WHERE t.kind = 'gold'), count(*) FILTER (WHERE t.kind = 'gold' AND t.verdict = 'wrong')
    FROM truth_signals t LEFT JOIN capabilities c ON c.id = t.capability_id
    WHERE t.created_at >= :t0 AND t.created_at < :t1 GROUP BY 1, 2
    """
)
_TOTALS = text(
    "SELECT area, sum(searches), sum(accepted_values), sum(wrong_values) FROM acq_daily "
    "WHERE day >= :d0 AND day <= :d1 GROUP BY 1"
)


class RollupRepo:
    """The roll-up's reads and writes."""

    @_store_errors
    async def day_counts(self, day: date) -> DayCounts:
        """The day's attempts, uncached searches and truth signals, grouped."""
        t0 = datetime(day.year, day.month, day.day, tzinfo=UTC)
        p = {"t0": t0, "t1": t0 + timedelta(days=1), "any": ANY_MARKET}
        async with sessionmaker()() as s:
            attempts = [AttemptCounts(str(a), str(m), int(n), int(v), int(q), float(c), float(e))
                        for a, m, n, v, q, c, e in (await s.execute(_ATTEMPTS, p)).all()]  # fmt: skip
            searches = [SearchCounts(str(a), int(n), float(c)) for a, n, c in (await s.execute(_SEARCHES, p)).all()]
            signals = [SignalCounts(str(a), str(m), int(w), int(g), int(gw))
                       for a, m, w, g, gw in (await s.execute(_SIGNALS, p)).all()]  # fmt: skip
        return DayCounts(attempts, searches, signals)

    @_store_errors
    async def write_day(self, day: date, rows: dict[tuple[str, str], DailyValues]) -> None:
        """The day's rows, inserted or replaced, in one transaction."""
        async with sessionmaker()() as s:
            for (area, market), vals in rows.items():
                stmt = insert(AcqDaily).values(day=day, area=area[:AREA_CHARS], market=market[:MARKET_CHARS], **vals)
                await s.execute(stmt.on_conflict_do_update(index_elements=["day", "area", "market"], set_=dict(vals)))
            await s.commit()

    @_store_errors
    async def area_totals(self, since: date, until: date) -> list[AreaTotals]:
        """Each area's sums over the days [since, until]."""
        async with sessionmaker()() as s:
            rows = (await s.execute(_TOTALS, {"d0": since, "d1": until})).all()
        return [AreaTotals(str(a), float(q or 0), float(v or 0), float(w or 0)) for a, q, v, w in rows]

    @_store_errors
    async def reset_exploration(self) -> None:
        """Today's exploration spend of every capability back to zero."""
        async with sessionmaker()() as s:
            await s.execute(update(CapabilityRow).values(explore_spent_eur=0.0))
            await s.commit()


class WorkerGauges:
    """The worker's Prometheus gauges (`acquisition.worker.exporter`)."""

    def set_reputation(self, searches_per_value: dict[str, float], wrong_share: dict[str, float],
                       components: dict[str, float], baseline_wrong_share: dict[str, float]) -> None:  # fmt: skip
        """Publish the reputation gauges."""
        exporter.set_reputation(searches_per_value, wrong_share, components, baseline_wrong_share)


class SystemToday:
    """Today in UTC."""

    def today(self) -> date:
        """Today's date (UTC)."""
        return datetime.now(UTC).date()
