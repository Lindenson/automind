"""Spec 011 US6 (T112, contracts/admin-api.md): the admin API of the acquisition engine — Parsers (versions, daily
metrics, drift signals, canary; rollback, freeze), Changes (engine and registry rows in one shape; revert, reject,
forbid similar), the accuracy drill-down to the page quote in three steps, the engine status strip; every route
refuses a request without the admin token."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from sqlalchemy import delete, select
from tests.fakes.reputation_world import World

from automind.acquisition.snapshots import store
from automind.api import admin
from automind.infrastructure import db
from automind.infrastructure.db import models as m

H = {"Authorization": "Bearer tok"}
QUOTE = "Potencia máxima 140 kW (190 CV) a 4.000 rpm"


def _client(monkeypatch) -> httpx.AsyncClient:
    monkeypatch.setattr(admin, "settings", lambda: type("S", (), {"admin_token": "tok"})())
    app = FastAPI()
    app.include_router(admin.router)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=("10.0.0.9", 1)), base_url="http://t")


def _spec(reader: str, v: int, label: str) -> dict[str, Any]:
    return {
        "reader": reader,
        "version": v,
        "domains": [f"{reader}.example"],
        "layout": "table",
        "fields": [{"attribute": "max_power", "label": label, "unit": "kW"}],
        "notes": f"v{v}",
    }


class Seed:
    """One reader with three versions (v1 superseded, v2 active and under watch, v3 rejected), 40 days of daily
    metrics, a drift journal row, the doctor's change v1→v2, a rule change in shadow and a registry change."""

    def __init__(self) -> None:
        self.tag = db.uid()[:8]
        self.reader = f"t6{self.tag}"
        self.domain = f"t6-{self.tag}.example"
        self.v1, self.v2, self.v3 = (f"{self.reader}@v{n}" for n in (1, 2, 3))
        self.drift_id = db.uid()
        self.doctor_id = db.uid()
        self.rule_id = db.uid()
        self.registry_id = ""
        self.cap_id = ""

    async def create(self) -> None:
        t = datetime.now(UTC)
        async with db.sessionmaker()() as s:
            s.add(m.Parser(reader=self.reader, domains=[f"{self.reader}.example"], active_version=2))
            await s.flush()
            for n, status, act in (
                (1, "superseded", t - timedelta(days=60)),
                (2, "active", t - timedelta(days=2)),
                (3, "rejected", None),
            ):
                s.add(
                    m.ParserVersion(
                        key=f"{self.reader}@v{n}",
                        reader=self.reader,
                        version=n,
                        spec=_spec(self.reader, n, f"Potencia v{n}"),
                        spec_hash=f"h{n}{self.tag}"[:12],
                        status=status,
                        author="seed" if n == 1 else "agent:parser_doctor",
                        change_id=self.doctor_id if n == 2 else None,
                        activated_at=act,
                    )
                )
            await s.flush()
            today = t.date()
            for i in range(40, 2, -1):  # v1: 11 fields a page, then the redesign 4 days ago drops it to 2
                d = today - timedelta(days=i)
                fpp = 11.0 if i > 4 else 2.0
                s.add(
                    m.ParserDaily(
                        version_key=self.v1,
                        day=d,
                        pages=10,
                        fields_total=int(fpp * 10),
                        fields_per_page=fpp,
                        rows_read=100,
                        rows_accepted=95,
                        pass_rate=0.95,
                        zero_pages=0,
                        structure_hash="aaaa",
                        structure_sim=1.0 if i > 4 else 0.3,
                    )
                )
            for i in range(2, -1, -1):
                s.add(
                    m.ParserDaily(
                        version_key=self.v2,
                        day=today - timedelta(days=i),
                        pages=9,
                        fields_total=99,
                        fields_per_page=11.0,
                        rows_read=90,
                        rows_accepted=88,
                        pass_rate=0.98,
                        zero_pages=0,
                        structure_hash="bbbb",
                        structure_sim=0.97,
                    )
                )
            s.add(
                m.AcqChange(
                    id=self.drift_id,
                    created_at=t - timedelta(days=3),
                    author="system",
                    object_kind="parser",
                    object_key=self.reader,
                    from_version=self.v1,
                    to_version=self.v1,
                    diff={"status": ["active", "degraded"]},
                    diff_hash="d1",
                    reason="drift:structure",
                    evidence={"signals": {"structure": {"sim": 0.3}, "yield_drop": {"ratio": 0.18}}},
                    gates={},
                    status="accepted",
                    explanation=f"{self.reader} parser v1 degraded: structure changed (similarity 0.30)",
                    cost_eur=0,
                    closed_at=t - timedelta(days=3),
                )
            )
            s.add(
                m.AcqChange(
                    id=self.doctor_id,
                    created_at=t - timedelta(days=2),
                    author="agent:parser_doctor",
                    object_kind="parser",
                    object_key=self.reader,
                    from_version=self.v1,
                    to_version=self.v2,
                    diff={"op": "replace", "path": "/fields/0/label", "from": "Potencia v1", "value": "Potencia v2"},
                    diff_hash="d2",
                    reason="drift:structure",
                    evidence={"snapshots": [], "gold": [], "counts": {"pages": 30}},
                    gates={
                        "replay": {"verdict": "pass", "metrics_old": {"yield": 0.42}, "metrics_new": {"yield": 0.91}},
                        "shadow": {"verdict": "pass"},
                        "watch": {"day": 2, "of": 7},
                        "future_gate": {"verdict": "pending", "extra": 1},
                    },
                    metrics_before={"fields_per_page": 2.0},
                    metrics_after={"fields_per_page": 11.0},
                    status="watch",
                    explanation=f"{self.reader} parser v1→v2: labels changed; v2 reproduces 48/50 gold "
                    f"values; shadow yield 0.91 vs 0.42",
                    cost_eur=0.03,
                )
            )
            s.add(
                m.AcqChange(
                    id=self.rule_id,
                    created_at=t - timedelta(hours=5),
                    author="agent:rule_auditor",
                    object_kind="rule",
                    object_key=f"plausibility.t6.{self.tag}.max",
                    from_version="300",
                    to_version="330",
                    diff={"value": [300, 330]},
                    diff_hash="d3",
                    reason="rule cluster",
                    evidence={},
                    gates={"replay": {"verdict": "pass"}},
                    status="shadow",
                    explanation="max raised 300→330: 12 right values were rejected",
                    cost_eur=0,
                )
            )
            s.add(
                m.SourceRow(
                    domain=self.domain,
                    source_type="PUBLICATION",
                    family=self.domain,
                    markets=["ES"],
                    access="ok",
                    frozen=False,
                )
            )
            await s.flush()
            cap = m.CapabilityRow(domain=self.domain, area="specs", market="ES", status="active")
            s.add(cap)
            await s.flush()
            self.cap_id = cap.id
            ch = m.RegistryChange(
                author="system",
                capability_id=cap.id,
                domain=self.domain,
                change="promoted",
                before={"status": "candidate"},
                after={"status": "active", "area": "specs"},
                reason="accuracy lower bound 0.87 passed 0.8",
                created_at=t - timedelta(hours=1),
            )
            s.add(ch)
            await s.flush()
            self.registry_id = ch.id
            await s.commit()

    async def drop(self) -> None:
        async with db.sessionmaker()() as s:
            await s.execute(
                delete(m.AcqChange).where(m.AcqChange.object_key.in_([self.reader, f"plausibility.t6.{self.tag}.max"]))
            )
            await s.execute(delete(m.Parser).where(m.Parser.reader == self.reader))
            await s.execute(delete(m.RegistryChange).where(m.RegistryChange.domain == self.domain))
            await s.execute(delete(m.CapabilityRow).where(m.CapabilityRow.domain == self.domain))
            await s.execute(delete(m.SourceRow).where(m.SourceRow.domain == self.domain))
            await s.commit()

    async def version(self, key: str) -> m.ParserVersion:
        async with db.sessionmaker()() as s:
            return (await s.execute(select(m.ParserVersion).where(m.ParserVersion.key == key))).scalar_one()

    async def parser(self) -> m.Parser:
        async with db.sessionmaker()() as s:
            return (await s.execute(select(m.Parser).where(m.Parser.reader == self.reader))).scalar_one()

    async def change(self, cid: str) -> m.AcqChange:
        async with db.sessionmaker()() as s:
            return (await s.execute(select(m.AcqChange).where(m.AcqChange.id == cid))).scalar_one()

    async def owner_rows(self) -> list[m.AcqChange]:
        async with db.sessionmaker()() as s:
            q = select(m.AcqChange).where(m.AcqChange.object_key == self.reader, m.AcqChange.author == "owner")
            return list((await s.execute(q.order_by(m.AcqChange.created_at))).scalars())


@pytest.fixture
async def seed():
    await db.init_db()
    s = Seed()
    await s.create()
    yield s
    await s.drop()


async def test_every_new_route_requires_the_token(monkeypatch, seed):
    c = _client(monkeypatch)
    routes = [r for r in admin.router.routes if isinstance(r, APIRoute)]
    assert len(routes) >= 20
    for r in routes:
        path = re.sub(r"\{[^}]+\}", "x", r.path)
        for method in r.methods:
            got = await c.request(method, path, json={})
            assert got.status_code == 403, (method, path, got.status_code)


async def test_parsers_list_and_detail(monkeypatch, seed):
    c = _client(monkeypatch)
    rows = (await c.get("/api/v1/admin/parsers", headers=H)).json()
    p = next(x for x in rows if x["reader"] == seed.reader)
    assert p["active"] == seed.v2 and p["frozen"] is False and p["domains"] == [f"{seed.reader}.example"]
    assert [v["key"] for v in p["versions"]] == [seed.v3, seed.v2, seed.v1]
    assert {v["key"]: v["status"] for v in p["versions"]}[seed.v1] == "superseded"
    assert p["last_7d"]["pages"] == 9 * 3 and p["last_7d"]["fields_per_page"] == pytest.approx(11.0)
    assert p["last_7d"]["pass_rate"] == pytest.approx(88 / 90, abs=1e-3)
    assert p["baseline_30d"]["fields_per_page"] is not None
    assert p["drift"] is None  # the drift of v1 is older than v2's activation
    assert p["canary"] == {"change_id": seed.doctor_id, "phase": "watch", "ends_at": None, "day": 2, "of": 7}

    one = (await c.get(f"/api/v1/admin/parsers/{seed.reader}", headers=H)).json()
    assert one["reader"] == seed.reader
    days = [d for d in one["daily"] if d["version_key"] == seed.v1]
    assert days and {
        "day",
        "pages",
        "fields_per_page",
        "pass_rate",
        "zero_pages",
        "structure_hash",
        "structure_sim",
    } <= set(days[0])
    assert len({d["day"] for d in one["daily"]}) <= 60
    kinds = {x["kind"] for x in one["drift_signals"]}
    assert {"structure", "yield_drop"} <= kinds
    assert all(x["version"] == seed.v1 and "structure changed" in x["detail"] for x in one["drift_signals"])
    assert one["specs"][seed.v2]["fields"][0]["label"] == "Potencia v2"
    assert (await c.get("/api/v1/admin/parsers/nope-nothing", headers=H)).status_code == 404


async def test_parser_rollback_and_freeze(monkeypatch, seed):
    c = _client(monkeypatch)
    url = f"/api/v1/admin/parsers/{seed.reader}"
    assert (await c.post(f"{url}/rollback", headers=H, json={"to": seed.v3})).status_code == 409  # never active
    assert (await c.post(f"{url}/rollback", headers=H, json={"to": seed.v2})).status_code == 409  # the current one
    assert (await c.post(f"{url}/rollback", headers=H, json={"to": "other@v1"})).status_code == 409
    r = await c.post(f"{url}/rollback", headers=H, json={"to": seed.v1})
    assert r.status_code == 200, r.text
    assert (await seed.version(seed.v1)).status == "active" and (await seed.version(seed.v2)).status == "superseded"
    assert (await seed.parser()).active_version == 1
    doctor = await seed.change(seed.doctor_id)
    owner = await seed.owner_rows()
    assert doctor.status == "reverted" and doctor.closed_at is not None and doctor.reverted_by == owner[-1].id
    assert owner[-1].from_version == seed.v2 and owner[-1].to_version == seed.v1 and owner[-1].closed_at
    assert "rolled back by the owner" in owner[-1].explanation

    assert (await c.post(f"{url}/freeze", headers=H)).status_code == 200
    assert (await seed.parser()).frozen is True
    assert (await c.get(url, headers=H)).json()["frozen"] is True
    assert (await c.post(f"{url}/unfreeze", headers=H)).status_code == 200
    assert (await seed.parser()).frozen is False
    owner = await seed.owner_rows()
    assert [o.diff.get("frozen") for o in owner[-2:]] == [[False, True], [True, False]]


async def test_changes_union_detail_and_filters(monkeypatch, seed):
    c = _client(monkeypatch)
    rows = (await c.get("/api/v1/admin/changes?days=30&limit=500", headers=H)).json()
    by_id = {r["id"]: r for r in rows}
    eng, reg = by_id[seed.doctor_id], by_id[seed.registry_id]
    assert set(eng) == set(reg)  # one shape
    assert eng["origin"] == "engine" and eng["author"] == "agent:parser_doctor" and eng["object_kind"] == "parser"
    assert eng["from_version"] == seed.v1 and eng["to_version"] == seed.v2 and eng["status"] == "watch"
    assert eng["gates"]["replay"]["verdict"] == "pass" and eng["gates"]["future_gate"]["verdict"] == "pending"
    assert eng["revertible"] is True and eng["rejectable"] is False
    assert reg["origin"] == "registry" and reg["object_kind"] == "source" and reg["object_key"] == seed.domain
    assert reg["explanation"] == "accuracy lower bound 0.87 passed 0.8" and reg["gates"] is None
    assert reg["from_version"] == "candidate" and reg["to_version"] == "active" and reg["revertible"] is True
    times = [r["created_at"] for r in rows]
    assert times == sorted(times, reverse=True)

    only = (await c.get("/api/v1/admin/changes?origin=registry", headers=H)).json()
    assert only and all(r["origin"] == "registry" for r in only)
    rules = (await c.get("/api/v1/admin/changes?object_kind=rule&agent=rule_auditor", headers=H)).json()
    assert [r["id"] for r in rules if r["id"] == seed.rule_id] == [seed.rule_id]
    assert all(r["object_kind"] == "rule" for r in rules)
    watch = (await c.get("/api/v1/admin/changes?status=watch", headers=H)).json()
    assert all(r["status"] == "watch" for r in watch)

    d = (await c.get(f"/api/v1/admin/changes/{seed.doctor_id}", headers=H)).json()
    assert d["diff"]["path"] == "/fields/0/label" and d["reason"] == "drift:structure"
    assert d["metrics_before"] == {"fields_per_page": 2.0} and d["metrics_after"] == {"fields_per_page": 11.0}
    assert d["gates"]["replay"]["metrics_new"] == {"yield": 0.91} and d["cost_eur"] == pytest.approx(0.03)
    assert d["evidence"]["counts"] == {"pages": 30}
    r = (await c.get(f"/api/v1/admin/changes/{seed.registry_id}", headers=H)).json()
    assert r["origin"] == "registry" and r["diff"] == {
        "before": {"status": "candidate"},
        "after": {"status": "active", "area": "specs"},
    }
    assert (await c.get(f"/api/v1/admin/changes/{db.uid()}", headers=H)).status_code == 404


async def test_change_revert_reject_and_forbid(monkeypatch, seed):
    c = _client(monkeypatch)
    base = "/api/v1/admin/changes"
    # a change still in its gates is rejected, not reverted
    assert (await c.post(f"{base}/{seed.rule_id}/revert", headers=H)).status_code == 409
    assert (await c.post(f"{base}/{seed.rule_id}/reject", headers=H)).status_code == 200
    rule = await seed.change(seed.rule_id)
    assert rule.status == "rejected" and rule.closed_at is not None and rule.gates["owner"]["reason"] == "owner"
    assert (await c.post(f"{base}/{seed.rule_id}/reject", headers=H)).status_code == 409
    # a drift journal row is not a revertible change
    assert (await c.post(f"{base}/{seed.drift_id}/revert", headers=H)).status_code == 409
    # the doctor's accepted change: revert re-activates its from_version
    r = await c.post(f"{base}/{seed.doctor_id}/revert", headers=H)
    assert r.status_code == 200, r.text
    assert (await seed.version(seed.v1)).status == "active" and (await seed.parser()).active_version == 1
    doctor = await seed.change(seed.doctor_id)
    assert doctor.status == "reverted" and doctor.reverted_by is not None
    assert (await c.post(f"{base}/{seed.doctor_id}/revert", headers=H)).status_code == 409
    # registry rows delegate to 010's revert
    assert (await c.post(f"{base}/{seed.registry_id}/revert", headers=H)).status_code == 200
    async with db.sessionmaker()() as s:
        assert (await s.get(m.RegistryChange, seed.registry_id)).reverted_by is not None
        assert (await s.get(m.CapabilityRow, seed.cap_id)).status == "candidate"
    # forbid similar = freeze the object: the parser and the registry source
    f = await c.post(f"{base}/{seed.doctor_id}/forbid-similar", headers=H, json={"days": 30})
    assert f.status_code == 200 and f.json()["frozen"] is True
    assert (await seed.parser()).frozen is True
    f = await c.post(f"{base}/{seed.registry_id}/forbid-similar", headers=H, json={"days": None})
    assert f.status_code == 200
    async with db.sessionmaker()() as s:
        assert (await s.get(m.SourceRow, seed.domain)).frozen is True


@pytest.fixture
async def wrong_value():
    """A reader claim of 190 kW whose gold is 140 kW: its page (a stored snapshot) says 140 kW, so the parser is
    blamed; returns (component, claim id, snapshot id, world)."""
    await db.init_db()
    w = World(f"t6{db.uid()[:6]}")
    domain = f"t6acc-{w.tag}.example"
    vid = await w.variant("A1")
    filler = "<p>" + ("Ficha técnica completa del coche con todos los datos. " * 120) + "</p>"
    html = f"<html><body><h1>Ficha</h1>{filler}<table><tr><td>{QUOTE}</td></tr></table>{filler}</body></html>"
    sid = await store.write(f"https://{domain}/a1", None, html.encode(), "text/html", 200, "OK", None)
    key = f"t6p{w.tag}@v4"
    [claim] = await w.page(
        vid,
        domain,
        "SPEC_DATABASE",
        QUOTE,
        [("max_power", 190.0, QUOTE)],
        producer="reader",
        producer_version=key,
        snapshot_id=sid,
    )
    component = f"parser:{key}"
    async with db.sessionmaker()() as s:
        s.add(
            m.TruthSignal(
                variant_id=vid,
                attribute="max_power",
                claim_id=claim,
                kind="gold",
                verdict="wrong",
                weight=1.0,
                blame="parser",
                blame_vector={"parser": 1.0},
                component=component,
                snapshot_id=sid,
                details={"gold": 140.0, "value": 190.0, "rule": "reference_set", "domain": domain, "area": "specs"},
            )
        )
        s.add(
            m.TruthSignal(
                variant_id=vid,
                attribute="max_power",
                claim_id=claim,
                kind="gold",
                verdict="right",
                weight=1.0,
                blame="source",
                component=f"source:{domain}",
                details={"domain": domain, "area": "specs"},
            )
        )
        s.add(m.ComponentReputation(kind="parser", key=key, right_w=10.0, wrong_w=1.0, acc_lb=0.62))
        today = date.today()
        await s.merge(
            m.AcqDaily(
                day=today,
                area=f"t6{w.tag}"[:20],
                market="ES",
                searches=4,
                pages=8,
                accepted_values=20,
                wrong_values=2,
                gold_checked=10,
                gold_wrong=2,
            )
        )
        await s.commit()
    yield component, claim, sid, w
    async with db.sessionmaker()() as s:
        await s.execute(delete(m.TruthSignal).where(m.TruthSignal.variant_id == vid))
        await s.execute(delete(m.ComponentReputation).where(m.ComponentReputation.key == key))
        await s.execute(delete(m.AcqDaily).where(m.AcqDaily.area == f"t6{w.tag}"[:20]))
        await s.commit()
    await w.cleanup()
    async with db.sessionmaker()() as s:
        await s.execute(delete(m.PageSnapshot).where(m.PageSnapshot.id == sid))
        await s.commit()


async def test_accuracy_drill_down_reaches_the_quote(monkeypatch, wrong_value):
    component, claim, sid, w = wrong_value
    c = _client(monkeypatch)
    acc = (await c.get("/api/v1/admin/accuracy?days=30", headers=H)).json()
    assert {"wrong_share", "baseline"} <= set(acc["kpi"])
    comp = next(x for x in acc["by_component"] if x["component"] == component)  # click 1
    assert comp["wrong"] == 1 and comp["acc_lb"] == pytest.approx(0.62) and comp["kind"] == "parser"
    area = next(x for x in acc["by_area"] if x["area"] == f"t6{w.tag}"[:20])
    assert area["wrong_share"] == pytest.approx(0.1) and area["gold_wrong"] == 2

    values = (await c.get(f"/api/v1/admin/accuracy/{component}/values?days=30", headers=H)).json()  # click 2
    [v] = [x for x in values if x["claim_id"] == claim]
    assert v["ours"] == 190.0 and v["truth"] == 140.0 and v["truth_origin"] == "gold:reference_set"
    assert v["attribute"] == "max_power" and v["blame_vector"] == {"parser": 1.0} and "A1" in v["variant"]

    one = (await c.get(f"/api/v1/admin/values/{claim}", headers=H)).json()  # click 3
    assert one["quote"] == QUOTE and one["producer"] == "reader" and one["producer_version"].endswith("@v4")
    assert one["snapshot"]["id"] == sid and one["evidence"]["domain"].startswith("t6acc-")
    assert one["signals"][0]["verdict"] in ("wrong", "right")
    page = await c.get(f"/api/v1/admin/snapshots/{sid}/text", headers=H, params={"around": QUOTE})
    assert page.status_code == 200 and page.headers["content-type"].startswith("text/plain")
    assert QUOTE in page.text and len(page.text) <= 4000 and "<td>" not in page.text
    assert (await c.get(f"/api/v1/admin/values/{db.uid()}", headers=H)).status_code == 404
    assert (await c.get(f"/api/v1/admin/snapshots/{db.uid()}/text", headers=H)).status_code == 404


async def test_engine_status(monkeypatch):
    await db.init_db()
    c = _client(monkeypatch)
    e = (await c.get("/api/v1/admin/engine", headers=H)).json()
    assert {"worker", "tasks", "budgets_today", "baseline", "autonomy", "open_changes"} <= set(e)
    assert isinstance(e["autonomy"], bool) and "scout" in e["budgets_today"]
    assert {"spent", "limit"} <= set(e["budgets_today"]["scout"])
