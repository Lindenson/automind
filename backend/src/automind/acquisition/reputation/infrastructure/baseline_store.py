"""The baseline's stores over the database: the windows (`kpi_baselines`) and the roll-up's KPIs (`acq_daily`). The
turns' outcomes are read by their owner (`observability.infrastructure.outcome_facts`); `delivery.baselines` wires
the service. A database failure becomes `BaselineStoreUnavailable` with the cause chained."""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from automind.acquisition.reputation import rollup
from automind.acquisition.reputation.application.baseline import BaselineStoreUnavailable, Window
from automind.acquisition.reputation.domain.baseline import BaselineValues, Kpis
from automind.shared.infrastructure.db.errors import translate_errors
from automind.shared.infrastructure.db.models import KpiBaseline
from automind.shared.infrastructure.db.session import sessionmaker

_store_errors = translate_errors(BaselineStoreUnavailable)


class BaselineRepo:
    """`kpi_baselines` rows as `Window`s."""

    @_store_errors
    async def latest(self, name: str) -> Window | None:
        async with sessionmaker()() as s:
            q = select(KpiBaseline).where(KpiBaseline.name == name)
            row = (await s.execute(q.order_by(KpiBaseline.started_at.desc()).limit(1))).scalar_one_or_none()
            return _window(row) if row is not None else None

    @_store_errors
    async def open_window(self, name: str) -> Window | None:
        async with sessionmaker()() as s:
            row = await _open(s, name)
            return _window(row) if row is not None else None

    @_store_errors
    async def open_windows(self) -> list[Window]:
        async with sessionmaker()() as s:
            rows = (await s.execute(select(KpiBaseline).where(KpiBaseline.ended_at.is_(None)))).scalars()
            return [_window(r) for r in rows]

    @_store_errors
    async def add(self, name: str, started_at: datetime, note: str | None) -> str:
        async with sessionmaker()() as s:
            row = KpiBaseline(name=name, started_at=started_at, values={}, note=note)
            s.add(row)
            await s.commit()
            return str(row.id)

    @_store_errors
    async def record(self, values: dict[str, BaselineValues], at: datetime) -> None:
        async with sessionmaker()() as s:
            for window_id, v in values.items():
                row = await s.get(KpiBaseline, window_id)
                if row is not None:
                    row.values, row.recorded_at = dict(v), at
            await s.commit()

    @_store_errors
    async def close(self, window_id: str, values: BaselineValues, at: datetime) -> None:
        async with sessionmaker()() as s:
            row = await s.get(KpiBaseline, window_id)
            if row is not None:
                row.values, row.recorded_at, row.ended_at = dict(values), at, at
            await s.commit()


class RollupKpis:
    """The KPIs of the daily roll-up (`reputation.rollup.kpis`)."""

    @_store_errors
    async def kpis(self, since: date, until: date) -> Kpis:
        k = await rollup.kpis(since, until)
        return {"searches_per_value": k["searches_per_value"], "wrong_share": k["wrong_share"]}


class SystemClock:
    """The system's time."""

    def now(self) -> datetime:
        return datetime.now(UTC)


async def _open(s: AsyncSession, name: str) -> KpiBaseline | None:
    q = select(KpiBaseline).where(KpiBaseline.name == name, KpiBaseline.ended_at.is_(None))
    return (await s.execute(q.order_by(KpiBaseline.started_at.desc()).limit(1))).scalar_one_or_none()


def _window(row: KpiBaseline) -> Window:
    return Window(id=str(row.id), name=row.name, started_at=row.started_at, ended_at=row.ended_at,
                  values=dict(row.values or {}), recorded_at=row.recorded_at, note=row.note)  # fmt: skip
