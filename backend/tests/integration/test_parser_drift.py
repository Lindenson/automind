"""US4 independent test (spec 011 T091, FR-016, AS-2/AS-3): 30 days of km77 pages in the old markup, then 15 pages of
the redesigned site (same values, new markup and labels) — the next `drift` task marks `km77@v1` degraded with
"structure changed" and the fields-per-page drop, journals it and queues the parser doctor; and five pages in a row
with no field mark it degraded at once, outside the daily task."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

import pytest
from sqlalchemy import delete, select, text, update

from automind.acquisition.parsing.infrastructure import v1_specs
from automind.acquisition.parsing.infrastructure import wiring as parsing_wiring
from automind.acquisition.snapshots import store
from automind.acquisition.worker import exporter
from automind.acquisition.worker.config import worker_config
from automind.acquisition.worker.process import Worker
from automind.shared.contracts.web import Page
from automind.shared.infrastructure import db

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "html"
OLD = [(FIX / "km77_three" / f"car_{c}.html").read_bytes() for c in "abc"]
NEW = [(FIX / "redesign" / f"km77_{c}.html").read_bytes() for c in "abc"]
DAY = date(2021, 6, 30)  # far from the pages other tests store today
KEY = "km77@v1"


async def _snapshot(raw: bytes, at: datetime, n: int) -> str:
    url = f"https://www.km77.com/coches/bmw/serie-5/2017/drift-{n}-{db.uid()[:8]}/datos"
    sid = await store.write(url, url, raw, "text/html", 200, "OK", None)
    async with db.sessionmaker()() as s:
        await s.execute(update(db.PageSnapshot).where(db.PageSnapshot.id == sid)
                        .values(fetched_at=at, parser_version=KEY))  # fmt: skip
        await s.commit()
    return sid


async def _reset_version() -> None:
    async with db.sessionmaker()() as s:
        await s.execute(update(db.ParserVersion).where(db.ParserVersion.key == KEY)
                        .values(status="active", degraded_reason=None, zero_streak=0))  # fmt: skip
        await s.execute(delete(db.AcqTask).where(db.AcqTask.dedupe_key == f"doctor:{KEY}"))
        await s.commit()


@pytest.fixture
async def world():
    await db.init_db()
    await v1_specs.seed()
    await _reset_version()
    started = datetime.now(UTC)
    sids: list[str] = []
    async with db.sessionmaker()() as s:
        src = await s.get(db.SourceRow, "km77.com")
        old_access = src.access if src is not None else None
        if src is None:
            s.add(db.SourceRow(domain="km77.com", source_type="SPEC_DATABASE", family="km77.com", markets=["ES"],
                               languages=["es"], access="ok", access_evidence={}, frozen=False))  # fmt: skip
        else:
            src.access = "ok"  # the reader runs only for a registry source with access "ok"
        await s.commit()
    yield sids
    async with db.sessionmaker()() as s:
        await s.execute(delete(db.PageSnapshot).where(db.PageSnapshot.id.in_(sids)))
        lo = DAY - timedelta(days=40)
        await s.execute(delete(db.ParserDaily).where(db.ParserDaily.day.between(lo, DAY)))
        await s.execute(delete(db.AcqChange).where(db.AcqChange.object_key == "km77",
                                                   db.AcqChange.created_at >= started))  # fmt: skip
        await s.execute(delete(db.AcqTask).where(db.AcqTask.kind == "drift", db.AcqTask.created_at >= started))
        if old_access is None:
            await s.execute(delete(db.SourceRow).where(db.SourceRow.domain == "km77.com"))
        else:
            await s.execute(update(db.SourceRow).where(db.SourceRow.domain == "km77.com").values(access=old_access))
        await s.commit()
    await _reset_version()


def _gauge(g, **labels: str) -> float | None:
    for metric in g.collect():
        for smp in metric.samples:
            if smp.labels == labels:
                return float(smp.value)
    return None


async def _changes(since: datetime) -> list[db.AcqChange]:
    async with db.sessionmaker()() as s:
        q = select(db.AcqChange).where(db.AcqChange.object_key == "km77", db.AcqChange.created_at >= since)
        return list((await s.execute(q.order_by(db.AcqChange.created_at))).scalars())


async def test_redesign_is_detected_by_the_daily_drift_task(world, capsys):
    started = datetime.now(UTC)
    noon = time(12, tzinfo=UTC)
    for i in range(30, 0, -1):  # one old-markup page a day for 30 days
        world.append(await _snapshot(OLD[i % 3], datetime.combine(DAY - timedelta(days=i), noon), i))
    for i in range(15):  # the redesign: 15 pages on DAY
        world.append(await _snapshot(NEW[i % 3], datetime.combine(DAY, noon) + timedelta(minutes=i), 100 + i))

    row = await Worker(worker_config()).once("drift", {"day": DAY.isoformat()})
    assert row["state"] == "done", row
    assert row["result"]["degraded"].keys() == {KEY}

    async with db.sessionmaker()() as s:
        v = await s.get(db.ParserVersion, KEY)
        day = await s.get(db.ParserDaily, (KEY, DAY))
        before = await s.get(db.ParserDaily, (KEY, DAY - timedelta(days=1)))
        doctor = (await s.execute(select(db.AcqTask).where(db.AcqTask.dedupe_key == f"doctor:{KEY}"))).scalar_one()
    assert v.status == "degraded"
    assert v.degraded_reason.startswith("structure changed") and "fields per page" in v.degraded_reason
    assert day.pages == 15 and day.fields_per_page == 3 and day.structure_sim < 0.6
    assert before.fields_per_page == 16 and before.structure_sim == 1.0
    assert doctor.kind == "parser_doctor" and doctor.state == "queued" and doctor.payload["version"] == KEY
    assert "parser_doctor" not in Worker(worker_config()).skip  # US5 T105: the doctor has its handler

    (change,) = await _changes(started)
    assert (change.author, change.object_kind, change.status, change.from_version) == ("system", "parser",
                                                                                        "accepted", KEY)  # fmt: skip
    assert change.reason == "drift:structure" and change.closed_at is not None
    assert change.explanation.startswith("km77 parser v1 degraded: structure changed")
    assert doctor.payload["change_id"] == change.id
    assert _gauge(exporter.PARSER_DRIFT, reader="km77") == 1.0
    with capsys.disabled():
        print(f"\n[drift demo] {change.explanation}")

    again = await Worker(worker_config()).once("drift", {"day": DAY.isoformat()})
    assert again["state"] == "done" and again["result"]["degraded"] == {}  # already degraded: journalled once
    assert len(await _changes(started)) == 1


async def test_five_empty_pages_in_a_row_degrade_at_once(world, capsys):
    started = datetime.now(UTC)
    reg = parsing_wiring.parser_registry(live=True)
    await reg.refresh()
    assert reg.from_db and reg.version_for("https://www.km77.com/x") is not None
    good = Page(url="https://www.km77.com/coches/a/datos", title="t", text="", html=OLD[0].decode("utf-8"))
    empty = "<html><body><p>Página en mantenimiento</p></body></html>"
    assert reg.read(good, {}) is not None
    for i in range(4):
        assert reg.read(Page(url=f"https://www.km77.com/coches/{i}/datos", title="t", text="", html=empty), {}) is None
    await reg.flush_stats()
    async with db.sessionmaker()() as s:
        v = await s.get(db.ParserVersion, KEY)
    assert (v.status, v.zero_streak) == ("active", 4)

    reg.read(Page(url="https://www.km77.com/coches/5/datos", title="t", text="", html=empty), {})
    await reg.flush_stats()
    async with db.sessionmaker()() as s:
        v = await s.get(db.ParserVersion, KEY)
        queued = (await s.execute(text("SELECT count(*) FROM acq_tasks WHERE dedupe_key = :k"),
                                  {"k": f"doctor:{KEY}"})).scalar_one()  # fmt: skip
    assert v.status == "degraded" and v.degraded_reason == "5 pages in a row with no fields"
    assert queued == 1
    (change,) = await _changes(started)
    assert change.reason == "drift:zero_streak"
    assert change.explanation.startswith("km77 parser v1 degraded: 5 pages in a row with no fields since ")
    with capsys.disabled():
        print(f"\n[zero-streak demo] {change.explanation}")

    # a degraded version keeps running: its readings still pass validation until a replacement is accepted
    assert reg.read(good, {}) is not None
