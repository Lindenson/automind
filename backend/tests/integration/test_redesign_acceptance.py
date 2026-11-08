"""US5 independent test (spec 011 T109, SC-007, SC-008; quickstart section 5): a simulated redesign of km77 — stored
pages substituted by the new markup — is detected, repaired by the parser doctor, passes the replay gate on gold and
stored pages and the shadow gate on the next prefetch pages, is accepted and journalled in one sentence with numbers,
with no human action; a deliberately worse proposal is rejected at the replay gate; an accepted change that degrades in
the watch is rolled back automatically. The worker runs in-process; the model answers are recorded fixtures."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

import pytest
from sqlalchemy import delete, func, select, text, update
from tests.fakes.fake_llm import FakeLLM

from automind.acquisition.agents import parser_doctor
from automind.acquisition.gold import repo
from automind.acquisition.gold.domain.match import GoldValue
from automind.acquisition.infrastructure import overrides
from automind.acquisition.parsing.infrastructure import v1_specs
from automind.acquisition.parsing.infrastructure import wiring as parsing_wiring
from automind.acquisition.snapshots import store
from automind.acquisition.worker.config import worker_config
from automind.acquisition.worker.process import Worker
from automind.shared.contracts.web import Page
from automind.shared.infrastructure import db
from automind.shared.infrastructure.config.loader import config_dir

FIX = Path(__file__).resolve().parents[1] / "fixtures"
OLD = [(FIX / "html" / "km77_three" / f"car_{c}.html").read_bytes() for c in "abc"]
NEW = [(FIX / "html" / "redesign" / f"km77_{c}.html").read_bytes() for c in "abc"]
V2 = json.loads((FIX / "agents" / "parser_doctor_km77_v2.json").read_text(encoding="utf-8"))
V3_WORSE = json.loads((FIX / "agents" / "parser_doctor_km77_v3_worse.json").read_text(encoding="utf-8"))
CARS = [("520d", 140.0, 400.0, 1615.0, 1995.0), ("530d", 195.0, 620.0, 1735.0, 2993.0),
        ("520i", 135.0, 290.0, 1540.0, 1998.0)]  # fmt: skip
UNITS = {"max_power": "kW", "max_torque": "N·m", "curb_mass": "kg", "displacement": "cm3"}
TOL = {"max_power": ("rel", 0.02), "max_torque": ("rel", 0.03), "curb_mass": ("rel", 0.03), "displacement": ("abs", 10)}
DAY = date(2021, 3, 15)  # the redesign day, far from the pages other tests store
KEY = "km77@v1"
KINDS = ("drift", "parser_daily", "parser_doctor", "gate_replay", "gate_shadow", "watch", "evaluator")


def _config_digest() -> str:
    h = hashlib.sha256()
    for f in sorted(config_dir().rglob("*")):
        if f.is_file():
            h.update(f.name.encode() + f.read_bytes())
    return h.hexdigest()


async def _reset_parser() -> None:
    async with db.sessionmaker()() as s:
        await s.execute(update(db.ParserVersion).where(db.ParserVersion.key == KEY)
                        .values(status="active", degraded_reason=None, zero_streak=0))  # fmt: skip
        await s.execute(delete(db.ParserVersion).where(db.ParserVersion.reader == "km77", db.ParserVersion.version > 1))
        await s.execute(update(db.Parser).where(db.Parser.reader == "km77").values(active_version=1))
        await s.execute(delete(db.AcqTask).where(db.AcqTask.dedupe_key == f"doctor:{KEY}"))
        await s.commit()


async def _snapshot(raw: bytes, at: datetime, vid: str, n: int, version: str | None = KEY) -> str:
    url = f"https://www.km77.com/coches/bmw/serie-5/2017/accept-{n}-{db.uid()[:8]}/datos"
    sid = await store.write(url, url, raw, "text/html", 200, "OK", None)
    await store.mark(sid, 5, vid)
    async with db.sessionmaker()() as s:
        await s.execute(update(db.PageSnapshot).where(db.PageSnapshot.id == sid)
                        .values(fetched_at=at, parser_version=version))  # fmt: skip
        await s.commit()
    return sid


@pytest.fixture
async def world():
    """50 km77 pages in the old markup over the 3 weeks before DAY and 20 in the new markup on DAY, with gold."""
    await db.init_db()
    await v1_specs.seed()
    await _reset_parser()
    overrides.clear()
    started = datetime.now(UTC)
    async with db.sessionmaker()() as s:
        src = await s.get(db.SourceRow, "km77.com")
        old_access = src.access if src is not None else None
        if src is None:
            s.add(db.SourceRow(domain="km77.com", source_type="SPEC_DATABASE", family="km77.com", markets=["ES"],
                               languages=["es"], access="ok", access_evidence={}, frozen=False))  # fmt: skip
        else:
            src.access = "ok"
        await s.commit()
    await repo.upsert_dataset(repo.DatasetInfo(repo.REFERENCE_SET, "Reference vehicles", "reference_set", "internal"))
    vids: list[str] = []
    for name, kw, nm, kg, cc in CARS:
        async with db.sessionmaker()() as s:
            v = db.Variant(canonical_key=f"t109|bmw|{name}|{db.uid()}", make="BMW", model="Serie 5", generation="G30",
                           variant_name=name, powertrain="ICE", generation_years_from=2017,
                           generation_years_to=2023)  # fmt: skip
            s.add(v)
            await s.commit()
        vals = {"max_power": kw, "max_torque": nm, "curb_mass": kg, "displacement": cc}
        await repo.replace(repo.REFERENCE_SET, v.id, [
            GoldValue(variant_id=v.id, attribute=a, value_num=x, unit=UNITS[a], tolerance=TOL[a][1],
                      tolerance_kind=TOL[a][0], origin="reference_set", match_rule="reference_set", confidence="HIGH",
                      dataset_id=repo.REFERENCE_SET) for a, x in vals.items()])  # fmt: skip
        vids.append(v.id)
    sids: list[str] = []
    start = datetime.combine(DAY - timedelta(days=21), time(8), tzinfo=UTC)
    for i in range(50):  # old markup, spread over 21 days
        sids.append(await _snapshot(OLD[i % 3], start + timedelta(hours=10 * i), vids[i % 3], i))
    for i in range(20):  # the redesign on DAY
        at = datetime.combine(DAY, time(9), tzinfo=UTC) + timedelta(minutes=7 * i)
        sids.append(await _snapshot(NEW[i % 3], at, vids[i % 3], 100 + i))
    yield {"vids": vids, "sids": sids, "started": started}
    parser_doctor.LLM_OVERRIDE = None
    overrides.clear()
    async with db.sessionmaker()() as s:
        await s.execute(delete(db.PageSnapshot).where(db.PageSnapshot.id.in_(sids)))
        await s.execute(delete(db.TruthSignal).where(db.TruthSignal.component.like("parser:km77@%"),
                                                     db.TruthSignal.created_at >= started))  # fmt: skip
        await s.execute(delete(db.Variant).where(db.Variant.id.in_(vids)))
        await s.execute(delete(db.ParserDaily).where(db.ParserDaily.day.between(DAY - timedelta(days=40), DAY)))
        await s.execute(delete(db.AcqChange).where(db.AcqChange.object_key == "km77",
                                                   db.AcqChange.created_at >= started))  # fmt: skip
        await s.execute(delete(db.AcqTask).where(db.AcqTask.kind.in_(KINDS), db.AcqTask.created_at >= started))
        if old_access is None:
            await s.execute(delete(db.SourceRow).where(db.SourceRow.domain == "km77.com"))
        else:
            await s.execute(update(db.SourceRow).where(db.SourceRow.domain == "km77.com").values(access=old_access))
        await s.commit()
    await _reset_parser()


async def _drain(*kinds: str) -> int:
    return len(await Worker(worker_config(), kinds=list(kinds)).drain())


async def _change(started: datetime, *, author: str = "agent:parser_doctor") -> db.AcqChange:
    async with db.sessionmaker()() as s:
        q = (
            select(db.AcqChange)
            .where(db.AcqChange.object_key == "km77", db.AcqChange.author == author, db.AcqChange.created_at >= started)
            .order_by(db.AcqChange.created_at.desc())
        )
        return (await s.execute(q)).scalars().first()


async def _version(key: str) -> tuple[str, int | None]:
    async with db.sessionmaker()() as s:
        v = await s.get(db.ParserVersion, key)
        p = await s.get(db.Parser, "km77")
    return (v.status if v is not None else "missing"), p.active_version


async def _drift_and_doctor(answer: dict, times: int = 1) -> None:
    row = await Worker(worker_config()).once("drift", {"day": DAY.isoformat()})
    assert row["state"] == "done" and KEY in row["result"]["degraded"], row
    assert (await _version(KEY))[0] == "degraded"
    parser_doctor.LLM_OVERRIDE = FakeLLM().queue("parser_doctor", *([answer] * times))
    assert await _drain("parser_doctor") == 1


async def _prefetch_pages(vids: list[str], sids: list[str], n: int = 20) -> None:
    """The next prefetch pages of km77 (new markup) read by the live registry: the old version serves them, and the
    parse stage queues the shadow gate."""
    reg = parsing_wiring.parser_registry(live=True)
    await reg.refresh()
    for i in range(n):
        at = datetime.combine(DAY + timedelta(days=1), time(7), tzinfo=UTC) + timedelta(minutes=5 * i)
        sid = await _snapshot(NEW[i % 3], at, vids[i % 3], 200 + i, version=None)
        sids.append(sid)
        html = NEW[i % 3].decode("utf-8")
        reading = reg.read(Page(url=f"https://www.km77.com/coches/x/prefetch-{i}/datos", title="t", text="",
                                html=html, snapshot_id=sid), {})  # fmt: skip
        assert reading is not None and reading.reader == KEY  # the user still sees the old version's values
    await reg.flush_stats()


async def test_redesign_repaired_with_no_human_then_rolled_back_in_watch(world, capsys):
    started, vids, sids = world["started"], world["vids"], world["sids"]
    config_before = _config_digest()

    # 1-2. drift on the redesign → km77@v1 degraded → the parser doctor drafts km77@v2 (a ParserSpec, never code)
    await _drift_and_doctor(V2)
    change = await _change(started)
    assert change is not None and change.status == "proposed" and change.object_kind == "parser"
    assert (change.from_version, change.to_version) == (KEY, "km77@v2")
    assert (await _version("km77@v2"))[0] == "candidate"

    # 3a. the replay gate on gold and the stored pages
    assert await _drain("gate_replay") == 1
    change = await _change(started)
    replay = change.gates["replay"]
    assert change.status == "shadow" and replay["verdict"] == "pass", replay
    assert replay["degraded"] and "yield" in replay["better"]
    assert replay["metrics_new"]["gold_covered"] >= 20 and replay["metrics_new"]["accuracy"] >= 0.9
    assert replay["metrics_new"]["yield"] > replay["metrics_old"]["yield"]

    # 3b. the shadow gate on the next 20 prefetch pages, run by the worker (no work in the turn)
    await _prefetch_pages(vids, sids)
    async with db.sessionmaker()() as s:
        queued = (await s.execute(select(func.count()).select_from(db.AcqTask).where(
            db.AcqTask.kind == "gate_shadow", db.AcqTask.created_at >= started))).scalar_one()  # fmt: skip
    assert queued == 20
    assert await _drain("gate_shadow") == 20
    change = await _change(started)
    shadow = change.gates["shadow"]
    assert change.status == "watch" and shadow["verdict"] == "pass", shadow
    assert await _version("km77@v2") == ("active", 2) and (await _version(KEY))[0] == "superseded"

    # 4. one sentence with the numbers of the run
    m = re.fullmatch(r"km77 parser v1→v2: page layout changed on 15\.03; v2 reproduces (\d+)/(\d+) gold values; "
                     r"shadow yield (\d+\.\d\d) vs (\d+\.\d\d)", change.explanation)  # fmt: skip
    assert m, change.explanation
    assert int(m.group(1)) == replay["metrics_new"]["gold_match"] and int(m.group(2)) >= 20
    assert float(m.group(3)) > float(m.group(4))
    with capsys.disabled():
        print(f"\n[T109 accepted] {change.explanation}")

    # no human: only the system (drift) and the agent journalled; no file under config/ changed (SC-008)
    async with db.sessionmaker()() as s:
        authors = {a for (a,) in (await s.execute(select(db.AcqChange.author).where(
            db.AcqChange.object_key == "km77", db.AcqChange.created_at >= started))).all()}  # fmt: skip
    assert authors == {"system", "agent:parser_doctor"}
    assert _config_digest() == config_before

    # 6. degradation in the watch: 3 wrong values blamed to km77@v2 → the evaluator rolls back on its own
    async with db.sessionmaker()() as s:
        for i in range(3):
            s.add(db.TruthSignal(variant_id=vids[i], attribute="max_torque", kind="gold", verdict="wrong", weight=1.0,
                                 blame="parser", blame_vector={"parser": 1.0}, component="parser:km77@v2",
                                 details={"t109": True}))  # fmt: skip
        await s.commit()
    row = await Worker(worker_config()).once("evaluator")
    assert row["state"] == "done" and row["result"]["watch"] == {change.id: "rollback"}, row
    assert set(row["result"]["kpi"]) == {"sources", "processing"}
    change = await _change(started)
    assert change.status == "rolled_back" and change.reverted_by
    assert await _version(KEY) == ("degraded", 1) and (await _version("km77@v2"))[0] == "rejected"
    async with db.sessionmaker()() as s:  # the parser is degraded again: the doctor retries tomorrow
        retry = (await s.execute(select(db.AcqTask).where(db.AcqTask.dedupe_key.like(f"doctor:{KEY}:%"),
                                                          db.AcqTask.created_at >= started))).scalar_one()  # fmt: skip
    assert retry.state == "queued" and retry.run_at > datetime.now(UTC)
    restore = await _change(started, author="system")
    assert restore.id == change.reverted_by
    assert (
        change.explanation == "km77 parser v2 rolled back: 3 wrong values blamed to v2 in 1 day; previous v1 restored"
    )
    with capsys.disabled():
        print(f"[T109 rolled back] {change.explanation}")

    # 7. every journalled change is of a declarative kind; still no file under config/ changed
    async with db.sessionmaker()() as s:
        odd = (await s.execute(text("SELECT count(*) FROM acq_changes WHERE object_kind NOT IN "
                                    "('parser','prompt','role_model','rule','source')"))).scalar_one()  # fmt: skip
    assert odd == 0
    assert _config_digest() == config_before


async def test_worse_proposal_is_rejected_at_replay(world, capsys):
    """US5 AS-2: better yield than the broken version, worse accuracy against gold → rejected, reason journalled."""
    started = world["started"]
    await _drift_and_doctor(V3_WORSE, times=3)  # the doctor's self-replay flags it; after 3 drafts the gate decides
    change = await _change(started)
    assert change is not None and change.status == "proposed"
    assert await _drain("gate_replay") == 1
    change = await _change(started)
    replay = change.gates["replay"]
    assert change.status == "rejected" and change.closed_at is not None and replay["verdict"] == "fail"
    assert replay["metrics_new"]["yield"] > replay["metrics_old"]["yield"]  # better yield ...
    assert any(r.startswith("accuracy_lb") and "degraded object" in r for r in replay["reasons"])  # ... worse gold
    assert change.explanation.startswith(f"km77 parser v1→{change.to_version.split('@')[1]} rejected at replay: "
                                         "accuracy_lb")  # fmt: skip
    assert (await _version(str(change.to_version)))[0] == "rejected"
    assert await _version(KEY) == ("degraded", 1)  # the running version is untouched
    with capsys.disabled():
        print(f"\n[T109 rejected] {change.explanation}")
