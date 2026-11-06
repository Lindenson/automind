"""Spec 010 T011: /metrics access rules and no database on scrape (FR-030, FR-031)."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from automind.delivery.web import metrics as m
from automind.observability.metrics import heartbeat, prom


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(m.router)
    return app


def test_rules_token_and_networks():
    assert m.metrics_ok("Bearer s3cret", "8.8.8.8", "s3cret", "")
    assert not m.metrics_ok("Bearer nope", "127.0.0.1", "s3cret", "127.0.0.0/8")  # a token, when set, is required
    assert m.metrics_ok(None, "127.0.0.1", None, "127.0.0.0/8,172.16.0.0/12")
    assert m.metrics_ok(None, "172.18.0.5", None, "127.0.0.0/8,172.16.0.0/12")  # docker network
    assert not m.metrics_ok(None, "8.8.8.8", None, "127.0.0.0/8,172.16.0.0/12")
    assert not m.metrics_ok(None, "not-an-ip", None, "127.0.0.0/8")


def test_scrape_serves_snapshot_without_database(monkeypatch: pytest.MonkeyPatch):
    import automind.shared.infrastructure.db.session as session

    def boom(*a: object, **k: object) -> None:
        raise AssertionError("a scrape must not open a database session")

    monkeypatch.setattr(session, "sessionmaker", boom)
    monkeypatch.setattr(m, "settings", lambda: type("S", (), {"metrics_token": "t", "metrics_nets": ""})())
    snap = prom.Snapshot()
    snap.set("satisfaction_index", ("compare", "7d"), 0.42)
    prom.publish(snap)
    heartbeat.beat("insight", True, 600)
    client = TestClient(_app())
    assert client.get("/metrics").status_code == 403
    r = client.get("/metrics", headers={"Authorization": "Bearer t"})
    assert r.status_code == 200
    assert 'automind_satisfaction_index{kind="compare",window="7d"} 0.42' in r.text
    assert 'automind_loop_interval_seconds{loop="insight"} 600.0' in r.text
