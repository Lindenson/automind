"""KPI baseline windows (spec 011 T073) over fake stores: the values of a window, the 7-day rule, one open window per
name, and a store failure that leaves the window as it was."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from automind.acquisition.reputation.application.baseline import (
    BaselineAlreadyOpen,
    BaselineStoreUnavailable,
    BaselineTooYoung,
    KpiBaselines,
    NoOpenBaseline,
    Window,
)
from automind.acquisition.reputation.domain.baseline import (
    BaselineValues,
    Kpis,
    Satisfaction,
    baseline_values,
    may_close,
)
from automind.shared.contracts.json import JsonObject

T0 = datetime(2026, 11, 5, 18, 11, tzinfo=UTC)


class _Store:
    def __init__(self, *, fail_writes: bool = False) -> None:
        self.windows: dict[str, Window] = {}
        self.fail_writes = fail_writes

    async def latest(self, name: str) -> Window | None:
        same = [w for w in self.windows.values() if w.name == name]
        return max(same, key=lambda w: w.started_at) if same else None

    async def open_window(self, name: str) -> Window | None:
        return next((w for w in self.windows.values() if w.name == name and w.ended_at is None), None)

    async def open_windows(self) -> list[Window]:
        return [w for w in self.windows.values() if w.ended_at is None]

    async def add(self, name: str, started_at: datetime, note: str | None) -> str:
        wid = f"w{len(self.windows) + 1}"
        self.windows[wid] = Window(wid, name, started_at, None, {}, None, note)
        return wid

    async def record(self, values: dict[str, BaselineValues], at: datetime) -> None:
        self._check()
        for wid, v in values.items():
            w = self.windows[wid]
            self.windows[wid] = Window(w.id, w.name, w.started_at, None, dict(v), at, w.note)

    async def close(self, window_id: str, values: BaselineValues, at: datetime) -> None:
        self._check()
        w = self.windows[window_id]
        self.windows[window_id] = Window(w.id, w.name, w.started_at, at, dict(values), at, w.note)

    def _check(self) -> None:
        if self.fail_writes:
            raise BaselineStoreUnavailable("kpi_baselines: OperationalError")


class _Outcomes:
    async def satisfaction(self, start: datetime, end: datetime) -> Satisfaction:
        return Satisfaction(0.8, 10)

    async def report_signals(self, start: datetime, end: datetime) -> list[JsonObject]:
        return [{"nodata_items": [{"area": "price"}]}, {}, {"nodata_items": [{"area": "price"}, {"area": "specs"}]}, {}]


class _Kpis:
    async def kpis(self, since: date, until: date) -> Kpis:
        return {"searches_per_value": {"specs": 0.5}, "wrong_share": {"specs": 0.1}}


class _Clock:
    def __init__(self, now: datetime) -> None:
        self.t = now

    def now(self) -> datetime:
        return self.t


def _service(store: _Store, now: datetime) -> KpiBaselines:
    return KpiBaselines(store, _Outcomes(), _Kpis(), _Clock(now))


def test_values_count_reports_with_an_area_without_data() -> None:
    signals: list[JsonObject] = [{"nodata_items": [{"area": "price"}]}, {}, {"nodata_items": [{"area": "price"}]}, {}]
    v = baseline_values({"searches_per_value": {}, "wrong_share": {"specs": 0.1}}, Satisfaction(None, 0), signals,
                        T0, T0 + timedelta(days=7))  # fmt: skip
    assert v["nodata_share"] == {"price": 0.5} and v["coverage"] == 0.5 and v["reports"] == 4 and v["days"] == 7.0
    assert v["accuracy_share_wrong"] == {"specs": 0.1} and v["satisfaction_index"] is None


def test_no_report_means_no_coverage() -> None:
    v = baseline_values({"searches_per_value": {}, "wrong_share": {}}, Satisfaction(None, 0), [], T0, T0)
    assert v["coverage"] is None and v["nodata_share"] == {}


def test_a_window_closes_after_seven_days() -> None:
    assert not may_close(T0, T0 + timedelta(days=6, hours=23))
    assert may_close(T0, T0 + timedelta(days=7))


async def test_one_open_window_per_name_and_close_after_a_week() -> None:
    store = _Store()
    svc = _service(store, T0 + timedelta(days=2))
    await svc.start("pre-autonomy", at=T0)
    with pytest.raises(BaselineAlreadyOpen):
        await svc.start("pre-autonomy")
    with pytest.raises(BaselineTooYoung, match="2.0 days"):
        await svc.close("pre-autonomy")
    assert await svc.record_open() == ["pre-autonomy"]
    values = await svc.close("pre-autonomy", now=T0 + timedelta(days=7, minutes=1))
    assert values["coverage"] == 0.5 and values["nodata_share"] == {"price": 0.5, "specs": 0.25}
    window = await svc.status("pre-autonomy")
    assert window is not None and window.ended_at is not None and window.values["turns"] == 10
    with pytest.raises(NoOpenBaseline):
        await svc.close("pre-autonomy")


async def test_a_failed_write_leaves_the_window_open() -> None:
    store = _Store()
    await _service(store, T0).start("pre-autonomy", at=T0)
    store.fail_writes = True
    with pytest.raises(BaselineStoreUnavailable):
        await _service(store, T0 + timedelta(days=8)).close("pre-autonomy")
    window = await store.open_window("pre-autonomy")
    assert window is not None and window.ended_at is None
