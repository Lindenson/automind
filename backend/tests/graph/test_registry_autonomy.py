"""Spec 010 US7 (T068, T070): the review promotes, demotes and blocks by the rules, holds frozen sources,
journals every change, and the owner can revert; hard limits refuse reverting into a forbidden state."""

from __future__ import annotations

from datetime import timedelta

import httpx
from fastapi import FastAPI
from sqlalchemy import delete, select

from automind.acquisition.registry.infrastructure.wiring import daily_review
from automind.delivery.web import admin
from automind.shared.infrastructure.config.loader import load_yaml
from automind.shared.infrastructure.db import models as m
from automind.shared.infrastructure.db.models import now
from automind.shared.infrastructure.db.session import sessionmaker


async def _setup() -> None:
    async with sessionmaker()() as s:
        for t in (m.RegistryAttempt, m.RegistryChange, m.TruthSignal, m.CapabilityRow, m.SourceRow):
            await s.execute(delete(t))
        old = now() - timedelta(days=2)
        for dom, access, frozen in (
            ("good.example", "ok", False),
            ("bad.example", "ok", False),
            ("forbid.example", "terms_forbid", False),
            ("frozen.example", "ok", True),
            ("new.example", "ok", False),
        ):
            s.add(
                m.SourceRow(
                    domain=dom,
                    source_type="PUBLICATION",
                    family=dom,
                    access=access,
                    frozen=frozen,
                    access_evidence={"clause": "automated access prohibited"} if access != "ok" else {},
                )
            )
        await s.flush()
        rows = [
            ("good.example", "candidate", 20, 15, 30.0, 0.0, [True] * 10),
            ("bad.example", "active", 20, 0, 0.0, 0.0, [False] * 10),
            ("forbid.example", "candidate", 20, 15, 30.0, 0.0, [True] * 10),
            ("frozen.example", "active", 20, 0, 0.0, 0.0, [False] * 10),
            ("new.example", "discovered", 1, 1, 0.0, 0.0, [True]),
        ]
        for dom, status, att, acc, right, wrong, recent in rows:
            s.add(
                m.CapabilityRow(
                    domain=dom,
                    area="specs",
                    market="ES",
                    status=status,
                    attempts=att,
                    accepted=acc,
                    right_w=right,
                    wrong_w=wrong,
                    signals_w=right + wrong,  # spec 011 FR-012: these are accuracy signals
                    recent=recent,
                    status_since=old,
                    decayed_at=now(),
                )
            )
        await s.commit()


async def _status() -> dict[str, str]:
    async with sessionmaker()() as s:
        return {c.domain: c.status for c in (await s.execute(select(m.CapabilityRow))).scalars()}


def _client(monkeypatch) -> httpx.AsyncClient:
    monkeypatch.setattr(admin, "settings", lambda: type("S", (), {"admin_token": "tok"})())
    app = FastAPI()
    app.include_router(admin.router)
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t", headers={"Authorization": "Bearer tok"}
    )


async def test_review_moves_journals_and_owner_reverts(monkeypatch):
    await _setup()
    cfg = {**load_yaml("registry.yaml"), "autonomy": True}
    stats = await daily_review(cfg).run(kind="test", admit_sites=False)
    st = await _status()
    assert st["good.example"] == "active" and st["bad.example"] == "degraded"
    assert st["forbid.example"] == "blocked" and st["frozen.example"] == "active" and st["new.example"] == "candidate"
    assert stats["held"] == 1
    c = _client(monkeypatch)
    changes = (await c.get("/api/v1/admin/sources/changes?days=7")).json()
    by = {(x["domain"], x["change"]): x for x in changes}
    assert by[("good.example", "promoted")]["reason"].startswith("accuracy lower bound")
    assert by[("frozen.example", "demoted")]["held"] is True
    assert by[("forbid.example", "blocked")]["revertible"] is True
    r = await c.post(f"/api/v1/admin/sources/changes/{by[('forbid.example', 'blocked')]['id']}/revert")
    assert r.status_code == 409 and "hard limit" in r.json()["detail"]
    r = await c.post(f"/api/v1/admin/sources/changes/{by[('bad.example', 'demoted')]['id']}/revert")
    assert r.status_code == 200 and (await _status())["bad.example"] == "active"
    listing = (await c.get("/api/v1/admin/sources?area=specs")).json()
    assert listing["autonomy"] is False and listing["sources"][0]["rank"] == 1
    assert {x["domain"] for x in listing["sources"]} >= {"good.example", "bad.example", "forbid.example"}
    await daily_review(cfg).run(
        kind="test", admit_sites=False
    )  # the reverted demotion is not repeated without new evidence
    assert (await _status())["bad.example"] == "active"
    card = (await c.get("/api/v1/admin/sources/forbid.example")).json()
    assert card["source"]["access_evidence"]["clause"] and card["changes"]
    assert (await c.post("/api/v1/admin/sources/good.example/freeze")).status_code == 200
    await daily_review(cfg).run(kind="test", admit_sites=False)
    async with sessionmaker()() as s:
        assert (await s.get(m.SourceRow, "good.example")).frozen is True


async def test_review_does_nothing_without_autonomy():
    await _setup()
    stats = await daily_review({**load_yaml("registry.yaml"), "autonomy": False}).run(admit_sites=False)
    assert stats["changes"] == 0 and (await _status())["good.example"] == "candidate"


async def test_admission_admits_or_blocks_discovered_sites_with_evidence():
    from automind.acquisition.registry.domain.admission import AdmissionFacts
    from automind.acquisition.registry.infrastructure.wiring import site_admission

    await _setup()
    async with sessionmaker()() as s:
        for dom in ("fine.example", "nobots.example", "legal.example"):
            s.add(m.SourceRow(domain=dom, source_type="PUBLICATION", family=dom, access="unknown"))
            await s.flush()
            s.add(
                m.CapabilityRow(
                    domain=dom, area="specs", market="ES", status="discovered", decayed_at=now(), status_since=now()
                )
            )
        await s.commit()

    class Facts:
        async def gather(self, domain: str, sample: str | None) -> AdmissionFacts:
            return {
                "fine.example": AdmissionFacts(domain, True, False, None, None, 5000),
                "nobots.example": AdmissionFacts(domain, False, None),
                "legal.example": AdmissionFacts(
                    domain, True, True, "Automated extraction is prohibited.", "https://l/t", 5000
                ),
            }.get(domain, AdmissionFacts(domain, True, False, None, None, 5000))

    cfg = {**load_yaml("registry.yaml"), "autonomy": True}
    out = await site_admission(cfg, facts=Facts()).admit_pending()
    assert out["blocked"] == 2 and out["admitted"] >= 1
    await daily_review(cfg).run(kind="test", admit_sites=False)
    st = await _status()
    assert st["fine.example"] == "candidate" and st["nobots.example"] == "blocked" and st["legal.example"] == "blocked"
    async with sessionmaker()() as s:
        legal = await s.get(m.SourceRow, "legal.example")
    assert legal.access == "terms_forbid" and legal.access_evidence["clause"] == "Automated extraction is prohibited."
    assert legal.next_check_at is not None
