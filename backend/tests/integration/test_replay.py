"""US1 independent test (spec 011 T033): stored pages of three cars + gold; replaying km77@v1 scores high, a reader
with two labels swapped scores lower and names the wrong values; no network and no model call. US4 (T090): the
versions are parser specs — stored ones by key, candidates from a JSON file."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import delete, func, select

from automind.acquisition.gold import repo
from automind.acquisition.gold.domain.match import GoldValue
from automind.acquisition.parsing.infrastructure import v1_specs
from automind.acquisition.replay import command as cli
from automind.acquisition.replay.run import NoPages, ReplayRequest, run
from automind.acquisition.snapshots import store
from automind.shared.infrastructure import db
from automind.shared.provenance.versions import spec_hash

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "html" / "km77_three"
CARS = {  # page -> (variant name, kW, N·m, kg, cm3)
    "car_a": ("520d", 140.0, 400.0, 1615.0, 1995.0),
    "car_b": ("530d", 195.0, 620.0, 1735.0, 2993.0),
    "car_c": ("520i", 135.0, 290.0, 1540.0, 1998.0),
}
TEST_VERSION = 9000  # a version number no real parser reaches
UNITS = {"max_power": "kW", "max_torque": "N·m", "curb_mass": "kg", "displacement": "cm3"}
TOL = {"max_power": ("rel", 0.02), "max_torque": ("rel", 0.03), "curb_mass": ("rel", 0.03), "displacement": ("abs", 10)}


def _gold(vid: str, kw: float, nm: float, kg: float, cc: float) -> list[GoldValue]:
    vals = {"max_power": kw, "max_torque": nm, "curb_mass": kg, "displacement": cc}
    common = {"origin": "reference_set", "match_rule": "reference_set", "confidence": "HIGH",
              "dataset_id": repo.REFERENCE_SET}  # fmt: skip
    return [
        GoldValue(variant_id=vid, attribute=a, value_num=x, unit=UNITS[a], tolerance=TOL[a][1],
                  tolerance_kind=TOL[a][0], **common)
        for a, x in vals.items()
    ]  # fmt: skip


@pytest.fixture
async def seeded():
    await db.init_db()
    since = datetime.now(UTC)  # only the pages this test stores
    await repo.upsert_dataset(repo.DatasetInfo(repo.REFERENCE_SET, "Reference vehicles", "reference_set", "internal"))
    ids, sids = [], []
    for page, (name, kw, nm, kg, cc) in CARS.items():
        async with db.sessionmaker()() as s:
            v = db.Variant(canonical_key=f"replay|bmw|{name}|{db.uid()}", make="BMW", model="Serie 5",
                           generation="G30", variant_name=name, powertrain="ICE", generation_years_from=2017,
                           generation_years_to=2023)  # fmt: skip
            s.add(v)
            await s.commit()
        url = f"https://www.km77.com/coches/bmw/serie-5/2017/{page}-{db.uid()[:8]}"
        sid = await store.write(url, url, (FIX / f"{page}.html").read_bytes(), "text/html", 200, "OK", None)
        await store.mark(sid, 5, v.id)
        await repo.replace(repo.REFERENCE_SET, v.id, _gold(v.id, kw, nm, kg, cc))
        ids.append(v.id)
        sids.append(sid)
    yield since, ids, sids
    async with db.sessionmaker()() as s:
        await s.execute(delete(db.PageSnapshot).where(db.PageSnapshot.id.in_(sids)))
        await s.execute(delete(db.Variant).where(db.Variant.id.in_(ids)))
        await s.commit()


async def _llm_rows() -> int:
    async with db.sessionmaker()() as s:
        return int((await s.execute(select(func.count()).select_from(db.LLMCall))).scalar_one())


async def test_v1_vs_broken_v2(seeded, capsys):
    since, ids, _ = seeded
    llm_before = await _llm_rows()
    v1 = await run(ReplayRequest(reader="km77@v1", since=since, domains=["km77.com"]))
    assert v1.pages == 3 and v1.pages_with_fields == 3 and v1.yield_ > 0
    assert v1.gold_covered == 12 and v1.accuracy is not None and v1.accuracy >= 0.9
    assert v1.network_calls == 0 and v1.llm_calls == 0

    v2 = await run(ReplayRequest(reader_spec=str(FIX / "broken_v2.json"), since=since, domains=["km77.com"]))
    assert v2.version == "km77@v2"
    assert v2.accuracy is not None and v2.accuracy < v1.accuracy
    wrong = {m["attribute"] for m in v2.mismatches}
    assert wrong and wrong <= {"curb_mass", "max_torque"}
    torque = next(m for m in v2.mismatches if m["attribute"] == "max_torque")
    assert torque["variant_id"] in ids and torque["quote"].lower().startswith("peso")
    assert v2.network_calls == 0
    assert await _llm_rows() == llm_before  # no model was asked

    rc = await cli.main_async(["--reader", "km77@v1", "--since", "1h", "--domain", "km77.com", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert set(out) >= {"version", "period", "pages", "pages_with_fields", "fields_per_page", "rows_read",
                        "rows_accepted", "pass_rate", "gold_covered", "gold_match", "accuracy", "accuracy_lb",
                        "by_attribute", "mismatches", "duration_s", "network_calls", "llm_calls"}  # fmt: skip
    assert out["version"] == "km77@v1" and out["network_calls"] == 0 and out["llm_calls"] == 0


async def test_stored_version_from_the_database(seeded, capsys):
    """Spec 011 T090: `--reader km77@vN` replays a version stored in parser_versions."""
    since, _, _ = seeded
    await v1_specs.seed()
    body = json.loads((FIX / "broken_v2.json").read_text(encoding="utf-8"))
    key = f"km77@v{TEST_VERSION}"
    body["version"] = TEST_VERSION
    async with db.sessionmaker()() as s:
        await s.execute(delete(db.ParserVersion).where(db.ParserVersion.key == key))
        s.add(db.ParserVersion(key=key, reader="km77", version=TEST_VERSION, spec=body, spec_hash=spec_hash(body),
                               status="candidate", author="owner"))  # fmt: skip
        await s.commit()
    try:
        rc = await cli.main_async(["--reader", key, "--since", "1h", "--domain", "km77.com", "--json"])
        assert rc == 0 and json.loads(capsys.readouterr().out)["version"] == key
        v2 = await run(ReplayRequest(reader=key, since=since, domains=["km77.com"]))
        v1 = await run(ReplayRequest(reader="km77@v1", since=since, domains=["km77.com"]))
        assert v2.version == key and v2.pages == 3
        assert v2.mismatches and {m["attribute"] for m in v2.mismatches} <= {"curb_mass", "max_torque"}
        assert v2.accuracy is not None and v1.accuracy is not None and v2.accuracy < v1.accuracy
    finally:
        async with db.sessionmaker()() as s:
            await s.execute(delete(db.ParserVersion).where(db.ParserVersion.key == key))
            await s.commit()


async def test_exit_codes(seeded, capsys, tmp_path):
    assert await cli.main_async(["--reader", "km77@v7"]) == 2  # no such stored version
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"reader": "km77", "version": 3, "domains": ["auto-data.net"], "layout": "table",
                               "fields": [{"attribute": "warp", "label": "x"}]}))  # fmt: skip
    assert await cli.main_async(["--reader-spec", str(bad)]) == 2  # deny-listed domain, unknown attribute
    assert "deny-list" in capsys.readouterr().err
    assert await cli.main_async(["--extractor", "extract_specs@v2"]) == 3  # model calls need --allow-llm
    with pytest.raises(NoPages):
        await run(ReplayRequest(reader="km77@v1", since=datetime.now(UTC) + timedelta(days=1)))
    capsys.readouterr()
