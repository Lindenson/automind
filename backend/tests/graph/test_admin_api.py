"""Spec 010 US4 (T042): the admin API — top problems, one problem with its copy text, status changes, the token."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
from fastapi import FastAPI
from sqlalchemy import delete

from automind.api import admin
from automind.infrastructure.db import models as m
from automind.infrastructure.db.session import sessionmaker


def _client(monkeypatch, token: str | None = "tok") -> httpx.AsyncClient:
    monkeypatch.setattr(admin, "settings", lambda: type("S", (), {"admin_token": token})())
    app = FastAPI()
    app.include_router(admin.router)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=("10.0.0.9", 1)), base_url="http://t")


async def _seed(n: int) -> list[str]:
    ids = []
    async with sessionmaker()() as s:
        await s.execute(delete(m.InsightIssue))
        t = datetime.now(UTC)
        for k in range(n):
            i = m.InsightIssue(fingerprint=f"fp{k}", component="dialogue", klass="not_understood", key=f"k/{k}",
                               title=f"issue {k}", impact=float(k), count_7d=k, chats_7d=1, first_seen=t,
                               last_seen=t, examples=[{"chat_id": f"chat{k}", "quote": "q"}], status="open",
                               status_history=[],
                               diagnosis={"summary": "s", "likely_cause": "c", "verify": "v",
                                          "fix": {"kind": "config", "config_file": "sense.yaml",
                                                  "config_key": "magnitude.x.max", "suggested_value": "9"}},
                               )  # fmt: skip
            s.add(i)
            await s.flush()
            ids.append(i.id)
        await s.commit()
    return ids


async def test_top_problems_order_detail_and_status(monkeypatch):
    ids = await _seed(15)
    c = _client(monkeypatch)
    assert (await c.get("/api/v1/admin/problems")).status_code == 403
    h = {"Authorization": "Bearer tok"}
    top = (await c.get("/api/v1/admin/problems", headers=h)).json()
    assert len(top) == 10 and [p["title"] for p in top[:2]] == ["issue 14", "issue 13"] and top[0]["rank"] == 1
    assert top[0]["fix"]["kind"] == "config" and top[0]["example_chat"] == "chat14"
    one = (await c.get(f"/api/v1/admin/problems/{ids[14]}", headers=h)).json()
    assert "sense.yaml" in one["copy_text"] and "magnitude.x.max" in one["copy_text"]
    r = await c.patch(f"/api/v1/admin/problems/{ids[14]}", headers=h, json={"status": "fixed", "fixed_ref": "abc123"})
    assert r.status_code == 200 and r.json()["status"] == "fixed" and r.json()["fixed_ref"] == "abc123"
    assert r.json()["status_history"][-1]["by"] == "owner"
    top = (await c.get("/api/v1/admin/problems", headers=h)).json()
    assert "issue 14" not in [p["title"] for p in top]  # fixed issues leave the list
    r2 = await c.patch(f"/api/v1/admin/problems/{ids[1]}", headers=h, json={"status": "regression"})
    assert r2.status_code == 422
