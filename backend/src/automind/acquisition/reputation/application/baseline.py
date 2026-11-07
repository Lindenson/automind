"""KPI baseline windows before registry autonomy (spec 011 FR-014, T073): start a named window, refresh the values
of the open ones (the daily `baseline` task), show one, close it after `MIN_DAYS`. The owner switches
`registry.autonomy` on by hand after a closed baseline (T078): nothing here reads or writes it.

Errors: `BaselineAlreadyOpen`, `NoOpenBaseline`, `BaselineTooYoung` (all `BaselineError`: the person's request
cannot be done, nothing is written); `ReputationStoreUnavailable` when a store cannot be read or written (propagates;
a window is written in one transaction, so a failure leaves it as it was)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from automind.acquisition.reputation.domain.baseline import (
    MIN_DAYS,
    BaselineValues,
    Satisfaction,
    baseline_values,
    days_run,
    may_close,
)
from automind.acquisition.reputation.domain.rollup import Kpis
from automind.shared.contracts.json import JsonObject


class BaselineError(RuntimeError):
    """A baseline request that cannot be done (the message says why); nothing was written."""


class BaselineAlreadyOpen(BaselineError):
    """A window of the name is already open."""

    def __init__(self, name: str) -> None:
        super().__init__(f"baseline {name!r} is already open")


class NoOpenBaseline(BaselineError):
    """No window of the name is open."""

    def __init__(self, name: str) -> None:
        super().__init__(f"no open baseline {name!r}")


class BaselineTooYoung(BaselineError):
    """The window has run less than `MIN_DAYS`."""

    def __init__(self, name: str, days: float) -> None:
        super().__init__(f"baseline {name!r} has run {days:.1f} days; it needs at least {MIN_DAYS}")


@dataclass(frozen=True)
class Window:
    """A baseline window as stored. `values` is empty until the first recording."""

    id: str
    name: str
    started_at: datetime
    ended_at: datetime | None
    values: JsonObject
    recorded_at: datetime | None
    note: str | None

    def to_json(self) -> JsonObject:
        """The window as the CLI prints it."""
        return {
            "id": self.id,
            "name": self.name,
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "values": self.values,
            "recorded_at": self.recorded_at.isoformat() if self.recorded_at else None,
            "note": self.note,
        }


class BaselineStore(Protocol):
    """The baseline windows (table `kpi_baselines`). Raises `ReputationStoreUnavailable`."""

    async def latest(self, name: str) -> Window | None:
        """The newest window of the name, open or closed."""
        ...

    async def open_window(self, name: str) -> Window | None:
        """The newest open window of the name."""
        ...

    async def open_windows(self) -> list[Window]:
        """Every open window."""
        ...

    async def add(self, name: str, started_at: datetime, note: str | None) -> str:
        """A new open window; returns its id."""
        ...

    async def record(self, values: dict[str, BaselineValues], at: datetime) -> None:
        """The values of open windows (window id -> values) recorded at `at`, in one transaction."""
        ...

    async def close(self, window_id: str, values: BaselineValues, at: datetime) -> None:
        """The window's final values recorded and the window ended at `at`, in one transaction."""
        ...


class OutcomeFacts(Protocol):
    """What the turns' outcomes say over a period (table `turn_outcomes`). Raises `ReputationStoreUnavailable`."""

    async def satisfaction(self, start: datetime, end: datetime) -> Satisfaction:
        """The satisfaction of the finished turns (a turn waiting for confirmation is not finished)."""
        ...

    async def report_signals(self, start: datetime, end: datetime) -> list[JsonObject]:
        """The outcome signals of every report."""
        ...


class KpiSource(Protocol):
    """The daily roll-up's KPIs (`acq_daily`). Raises `ReputationStoreUnavailable`."""

    async def kpis(self, since: date, until: date) -> Kpis:
        """The KPIs over the days [since, until]."""
        ...


class Clock(Protocol):
    """The time of the system (a fixed one in tests)."""

    def now(self) -> datetime:
        """Now, timezone-aware."""
        ...


class KpiBaselines:
    """The baseline windows, with their store, the outcome facts, the roll-up's KPIs and the clock."""

    def __init__(self, store: BaselineStore, outcomes: OutcomeFacts, kpis: KpiSource, clock: Clock) -> None:
        self.store, self.outcomes, self.kpis, self.clock = store, outcomes, kpis, clock

    async def start(self, name: str, note: str | None = None, at: datetime | None = None) -> str:
        """A new window `name` from `at` (now); returns its id. Raises `BaselineAlreadyOpen`."""
        if await self.store.open_window(name) is not None:
            raise BaselineAlreadyOpen(name)
        return await self.store.add(name, at or self.clock.now(), note)

    async def status(self, name: str) -> Window | None:
        """The newest window of the name, None when there is none."""
        return await self.store.latest(name)

    async def close(self, name: str, now: datetime | None = None) -> BaselineValues:
        """The open window's final values, recorded as it ends. Raises `NoOpenBaseline`, `BaselineTooYoung`."""
        t = now or self.clock.now()
        window = await self.store.open_window(name)
        if window is None:
            raise NoOpenBaseline(name)
        if not may_close(window.started_at, t):
            raise BaselineTooYoung(name, days_run(window.started_at, t))
        values = await self.values(window.started_at, t)
        await self.store.close(window.id, values, t)
        return values

    async def record_open(self) -> list[str]:
        """The daily task: the values of every open window refreshed up to now; returns their names."""
        t = self.clock.now()
        windows = await self.store.open_windows()
        await self.store.record({w.id: await self.values(w.started_at, t) for w in windows}, t)
        return [w.name for w in windows]

    async def values(self, start: datetime, end: datetime) -> BaselineValues:
        """The baseline's values over [start, end] (read only)."""
        kpis = await self.kpis.kpis(start.date(), end.date())
        satisfaction = await self.outcomes.satisfaction(start, end)
        return baseline_values(kpis, satisfaction, await self.outcomes.report_signals(start, end), start, end)
