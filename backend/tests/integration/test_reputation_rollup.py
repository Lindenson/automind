"""Spec 011 T072-T073: the daily roll-up (searches per accepted value, wrong share, exploration reset, gauges) and the
KPI baseline window (refuses to close before 7 days; never touches registry.autonomy)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select
from tests.fakes.reputation_world import World

from automind.acquisition.registry.api import Attempt, TruthSignalIn
from automind.acquisition.registry.application.service import RegistryService
from automind.acquisition.registry.infrastructure.repo import RegistryRepo
from automind.acquisition.reputation import baseline, rollup
from automind.acquisition.worker import budget, exporter
from automind.acquisition.worker.handlers import HANDLERS
from automind.shared.infrastructure import db
from automind.shared.infrastructure.config.loader import load_yaml
from automind.shared.infrastructure.db import models as m

AREA = "rolltest"
DOM = "roll.example"


@pytest.fixture
async def world():
    await db.init_db()
    w = World("t072")
    await w.clear_registry()
    async with db.sessionmaker()() as s:
        await s.execute(delete(m.SearchCall).where(m.SearchCall.area == AREA))
        await s.execute(delete(m.AcqDaily).where(m.AcqDaily.area == AREA))
        await s.execute(delete(m.KpiBaseline).where(m.KpiBaseline.name.like("t072%")))
        await s.commit()
    yield w
    await w.cleanup()


def _gauge(g, **labels: str) -> float | None:
    for metric in g.collect():
        for smp in metric.samples:
            if smp.labels == labels:
                return float(smp.value)
    return None


async def test_rollup_counts_searches_per_value_and_resets_exploration(world: World) -> None:
    cfg = load_yaml("registry.yaml")
    svc = RegistryService(RegistryRepo(cfg), cfg)
    await world.source(DOM, "PUBLICATION", area=AREA)
    await svc.record([Attempt(domain=DOM, area=AREA, market="ES", url=f"https://{DOM}/{i}", outcome="accepted",
                              values=4, cost_eur=0.01) for i in range(5)])  # fmt: skip
    assert (await world.cap(DOM, AREA)).explore_spent_eur == pytest.approx(0.05)  # a candidate's attempts explore
    async with db.sessionmaker()() as s:
        for _ in range(10):
            s.add(m.SearchCall(area=AREA, provider="serper", kind="search", credits=1, cost_eur=0.001))
        s.add(m.SearchCall(area=AREA, provider="serper", kind="search", credits=0, cached=True))
        await s.commit()
    for verdict in ("wrong", "wrong", "right"):
        await svc.signal(TruthSignalIn(kind="gold", verdict=verdict, domain=DOM, area=AREA, claim_id=db.uid()))

    today = datetime.now(UTC).date()
    assert await rollup.roll_day(today) >= 2
    async with db.sessionmaker()() as s:
        rows = {r.market: r for r in (await s.execute(select(m.AcqDaily).where(m.AcqDaily.area == AREA))).scalars()}
    assert rows["*"].searches == 10  # cached searches cost nothing and are not counted
    es = rows["ES"]
    assert (es.pages, es.accepted_values, es.wrong_values, es.gold_checked, es.gold_wrong) == (5, 20, 2, 3, 2)
    assert float(es.explore_eur) == pytest.approx(0.05)
    k = await rollup.kpis(today)
    assert k["searches_per_value"][AREA] == pytest.approx(10 / 20) and k["wrong_share"][AREA] == pytest.approx(0.1)

    out = await rollup.run(today)
    assert out["rows"] >= 2
    assert (await world.cap(DOM, AREA)).explore_spent_eur == 0  # a new day of exploration budget
    assert _gauge(exporter.SEARCHES_PER_VALUE, area=AREA) == pytest.approx(0.5)
    assert _gauge(exporter.WRONG_SHARE, area=AREA) == pytest.approx(0.1)


async def test_baseline_window_needs_seven_days(world: World) -> None:
    name = "t072-pre-autonomy"
    autonomy = load_yaml("registry.yaml")["autonomy"]
    started = datetime.now(UTC) - timedelta(days=2)
    await baseline.start(name, "test", at=started)
    with pytest.raises(baseline.BaselineError, match="already open"):
        await baseline.start(name)
    with pytest.raises(baseline.BaselineError, match="needs at least 7"):
        await baseline.close(name)
    assert (await baseline.record_open())["open"] and (await baseline.status(name))["recorded_at"]
    values = await baseline.close(name, now=started + timedelta(days=7, minutes=1))
    assert {"accuracy_share_wrong", "searches_per_value", "satisfaction_index", "nodata_share", "coverage"} <= set(
        values
    )
    st = await baseline.status(name)
    assert st and st["ended_at"]
    assert await baseline.main_async(["close", "--name", name]) == 1  # nothing open any more
    assert load_yaml("registry.yaml")["autonomy"] is autonomy is False  # the owner switches it (T078)


def test_worker_has_the_reputation_tasks() -> None:
    assert {"reputation_signals", "rollup", "baseline", "blame_judge"} <= set(HANDLERS)
    assert budget.cap_for("blame_judge") == pytest.approx(0.05)
    schedule = load_yaml("acquisition.yaml")["schedule"]
    assert {"reputation_signals", "rollup", "baseline"} <= set(schedule)
