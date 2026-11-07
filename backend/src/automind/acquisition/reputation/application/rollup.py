"""The daily roll-up (spec 011 T072): the `acq_daily` rows of yesterday and today so far, today's exploration spend
reset, the components' reputation faded, and the worker's reputation gauges published — searches per accepted value
and wrong share by area (7 days), the components' accuracy by kind, and the last closed baseline's wrong share.

Errors: a store failure (`ReputationStoreUnavailable`) propagates from the roll-up and the resets; the gauges are
best effort — `run` logs their failure and goes on (a gauge left behind is harmless)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Protocol

from automind.acquisition.reputation.domain.components import Weights, mean_lb_by_kind
from automind.acquisition.reputation.domain.rollup import (
    AreaTotals,
    AttemptCounts,
    DailyValues,
    Kpis,
    SearchCounts,
    SignalCounts,
    daily_rows,
    kpis_of,
)
from automind.shared.contracts.json import JsonObject

log = logging.getLogger(__name__)
GAUGE_DAYS = 7


@dataclass(frozen=True)
class DayCounts:
    """What happened on one day, as the roll-up reads it."""

    attempts: list[AttemptCounts]
    searches: list[SearchCounts]
    signals: list[SignalCounts]


class RollupStore(Protocol):
    """The day's counts and the `acq_daily` rows. Raises `ReputationStoreUnavailable`."""

    async def day_counts(self, day: date) -> DayCounts:
        """The day's attempts, uncached searches and truth signals, grouped."""
        ...

    async def write_day(self, day: date, rows: dict[tuple[str, str], DailyValues]) -> None:
        """The day's rows by (area, market), replacing earlier ones, in one transaction."""
        ...

    async def area_totals(self, since: date, until: date) -> list[AreaTotals]:
        """Each area's sums over the days [since, until]."""
        ...

    async def reset_exploration(self) -> None:
        """Today's exploration spend of every capability back to zero."""
        ...


class ComponentStore(Protocol):
    """The components' reputation (`component_reputation`). Raises `ReputationStoreUnavailable`."""

    async def decay_all(self, half_life_days: float) -> int:
        """Every component faded to now; returns how many."""
        ...

    async def weights(self) -> list[tuple[str, Weights]]:
        """Every component's (kind, weights)."""
        ...


class LastBaseline(Protocol):
    """The KPI baselines as the gauges read them. Raises `ReputationStoreUnavailable`."""

    async def last_closed_wrong_share(self) -> dict[str, float]:
        """The wrong share by area of the last closed KPI baseline, {} when none closed."""
        ...


class Gauges(Protocol):
    """The worker's reputation gauges."""

    def set_reputation(self, searches_per_value: dict[str, float], wrong_share: dict[str, float],
                       components: dict[str, float], baseline_wrong_share: dict[str, float]) -> None:  # fmt: skip
        """Publish the reputation gauges."""
        ...


class Today(Protocol):
    """The calendar of the system (a fixed day in tests)."""

    def today(self) -> date:
        """Today's date (UTC)."""
        ...


class DailyRollup:
    """The roll-up with its stores, the gauges, the clock and the components' half-life (days)."""

    def __init__(self, store: RollupStore, components: ComponentStore, baselines: LastBaseline, gauges: Gauges,
                 clock: Today, half_life_days: float) -> None:  # fmt: skip
        self.store, self.components, self.baselines, self.gauges = store, components, baselines, gauges
        self.clock, self.half_life_days = clock, half_life_days

    async def run(self, day: date | None = None, reset: bool = True) -> JsonObject:
        """The daily `rollup` task: `day` (yesterday and today), then the resets (unless `reset` is False) and the
        gauges. Returns what it did (days, rows, components faded, gauges)."""
        today = self.clock.today()
        days = [day] if day else [today - timedelta(days=1), today]
        rows = 0
        for d in days:
            rows += await self.roll_day(d)
        out: JsonObject = {"days": [d.isoformat() for d in days], "rows": rows}
        if reset:
            await self.store.reset_exploration()
            out["components_faded"] = await self.components.decay_all(self.half_life_days)
        try:
            out.update(await self.publish_gauges())
        except Exception:  # noqa: BLE001 - the gauges are best effort (module docstring)
            log.exception("rollup.gauges_failed")
        return out

    async def roll_day(self, day: date) -> int:
        """The `acq_daily` rows of one day recomputed (idempotent); returns how many."""
        counts = await self.store.day_counts(day)
        rows = daily_rows(counts.attempts, counts.searches, counts.signals)
        await self.store.write_day(day, rows)
        return len(rows)

    async def kpis(self, since: date, until: date | None = None) -> Kpis:
        """The KPIs over the days [since, until (today)]."""
        return kpis_of(await self.store.area_totals(since, until or self.clock.today()))

    async def publish_gauges(self) -> JsonObject:
        """The gauges over the last `GAUGE_DAYS` days; returns how many areas and component kinds they show."""
        k = await self.kpis(self.clock.today() - timedelta(days=GAUGE_DAYS - 1))
        comp = mean_lb_by_kind(await self.components.weights())
        base = await self.baselines.last_closed_wrong_share()
        self.gauges.set_reputation(k["searches_per_value"], k["wrong_share"], comp, base)
        return {"areas": len(k["searches_per_value"]), "components": len(comp)}
