"""Access before any external demo: each browser sees only its own chats, other sites cannot drive the hub, the
operator endpoints are closed, and a daily spend cap pauses research with "continue?" (never cancels)."""

import httpx
import pytest
from sqlalchemy import update
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from automind.api import access
from automind.api.app import app
from automind.application.usage import Limits, Prices, TurnBudget
from automind.infrastructure import db
from automind.infrastructure.db.repositories import CaseRepo, ChatRepo, MessageRepo, TurnRepo


class _Bus:
    async def publish(self, *_a, **_k) -> None:
        return None


app.state.chats, app.state.cases, app.state.messages = ChatRepo(), CaseRepo(), MessageRepo()


class _Runner:
    async def cancel(self, _chat_id: str) -> None:
        return None

    def is_running(self, _chat_id: str) -> bool:
        return False


async def _no_thread(_chat_id: str) -> None:
    return None


app.state.bus, app.state.turns = _Bus(), TurnRepo()
app.state.runner, app.state.delete_thread = _Runner(), _no_thread
HOST = "http://hub.test"


def _client() -> httpx.AsyncClient:  # a browser somewhere on the network, not this machine
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=("203.0.113.9", 4000)), base_url=HOST)


async def test_each_browser_sees_only_its_own_chats():
    await db.init_db()
    chat = db.uid()
    async with _client() as alice, _client() as bob:
        assert (await alice.get("/api/v1/session")).json() == {"isolated": True}
        assert access.COOKIE in alice.cookies
        await bob.get("/api/v1/session")
        assert alice.cookies[access.COOKIE] != bob.cookies[access.COOKIE]

        r = await alice.patch(f"/api/v1/chats/{chat}/case", json={"annual_km": 18000})
        assert r.status_code == 200
        assert (await alice.get(f"/api/v1/chats/{chat}/case")).json()["case"]["annual_km"] == 18000
        for path in (f"/api/v1/chats/{chat}/case", f"/api/v1/chats/{chat}/messages", f"/api/v1/chats/{chat}/weights",
                     f"/api/chats/{chat}/messages"):  # fmt: skip
            got = await bob.get(path)
            assert got.status_code == 404 and got.json()["code"] == "chat_not_found", path
        assert (await bob.patch(f"/api/v1/chats/{chat}/case", json={"annual_km": 5000})).status_code == 404
        assert chat in [c["id"] for c in (await alice.get("/api/v1/chats")).json()["chats"]]
        assert chat not in [c["id"] for c in (await bob.get("/api/v1/chats")).json()["chats"]]
        # Bob cannot delete it either
        assert (await bob.post("/api/v1/chats/delete", json={"ids": [chat]})).json()["deleted"] == []
        assert (await alice.get(f"/api/v1/chats/{chat}/case")).status_code == 200


async def test_a_chat_from_before_owners_is_claimed_once():
    await db.init_db()
    chat = db.uid()
    await ChatRepo().ensure(chat)  # no owner: created before the upgrade
    async with _client() as first, _client() as second:
        assert (await first.get(f"/api/v1/chats/{chat}/messages")).status_code == 200
        assert (await second.get(f"/api/v1/chats/{chat}/messages")).status_code == 404


async def test_changes_from_another_site_are_refused():
    await db.init_db()
    async with _client() as c:
        await c.get("/api/v1/session")
        chat = db.uid()
        evil = await c.patch(f"/api/v1/chats/{chat}/case", json={"annual_km": 9000},
                             headers={"origin": "https://evil.example"})  # fmt: skip
        assert evil.status_code == 403 and evil.json()["code"] == "origin_refused"
        same = await c.patch(f"/api/v1/chats/{chat}/case", json={"annual_km": 9000}, headers={"origin": HOST})
        assert same.status_code == 200
        dev = await c.patch(f"/api/v1/chats/{chat}/case", json={"annual_km": 9500},
                            headers={"origin": "http://localhost:5173"})  # fmt: skip
        assert dev.status_code == 200
        # reading is not a change: another site cannot read the answer anyway (no CORS for it)
        assert (await c.get("/api/v1/criteria", headers={"origin": "https://evil.example"})).status_code == 200


def test_websocket_origin_check():
    client = TestClient(app)
    evil = {"origin": "https://evil.example"}
    with pytest.raises(WebSocketDisconnect) as e, client.websocket_connect("/ws/chat/x", headers=evil) as ws:
        ws.receive_json()
    assert e.value.code == 4403


async def test_operator_metrics_are_closed():
    async with _client() as c:  # the ASGI test client is not this machine's loopback
        r = await c.get("/api/v1/research/metrics")
        assert r.status_code == 403 and r.json()["code"] == "admin_only"
    assert access.admin_ok(None, "127.0.0.1", None)
    assert not access.admin_ok(None, "172.18.0.1", None)  # through Docker: not this machine
    assert access.admin_ok("Bearer s3cret", "203.0.113.9", "s3cret")
    assert not access.admin_ok("Bearer nope", "127.0.0.1", "s3cret")  # with a token set, the token decides


@pytest.mark.parametrize(
    ("origin", "host", "ok"),
    [
        (None, "hub.test", True),
        ("http://hub.test", "hub.test", True),
        ("http://localhost:5173", "127.0.0.1:8000", True),
        ("https://evil.example", "hub.test", False),
        ("http://hub.test.evil.example", "hub.test", False),
        ("null", "hub.test", False),
    ],
)
def test_origin_rules(origin, host, ok):
    assert access.origin_ok(origin, host, ["http://localhost:5173"]) is ok


def test_owner_cookie_values():
    t = access.new_token()
    assert access.owner_of(t) and len(access.owner_of(t)) == 64 and access.owner_of(t) != t
    assert (
        access.owner_of(None) is None and access.owner_of("short") is None and access.owner_of("x" * 33 + ";") is None
    )


def _budget(day_spent: float, cap: float = 5.0) -> TurnBudget:
    prices = Prices.from_config(
        {"default_llm": {"input": 0, "output": 0}, "search": {"eur_per_credit": 0, "credits": {}}}
    )
    return TurnBudget("c", "t", prices, Limits(hard_cap_eur=1.0, daily_cap_eur=cap), day_spent_eur=day_spent)


def test_daily_cap_pauses_and_continue_allows_one_more_allowance():
    assert _budget(1.0).research_pause() is None
    b = _budget(4.9)
    b.cost_eur = 0.12
    assert b.research_pause() == "daily"
    b.extend(1)  # the user said "continue": one more turn allowance past the cap
    assert b.research_pause() is None
    b.cost_eur = 1.2
    assert b.research_pause() in ("cost", "daily")
    assert _budget(100.0, cap=0).research_pause() is None  # 0 = no cap


async def test_spent_today_counts_all_chats_but_this_turn():
    await db.init_db()
    repo = TurnRepo()
    before = await repo.spent_today()
    turn = db.uid()
    async with db.sessionmaker()() as s:
        s.add(db.LLMCall(chat_id="c", turn_id=turn, role="t", model="m", cost_eur=0.25))
        s.add(db.LLMCall(chat_id="c", turn_id=db.uid(), role="t", model="m", cost_eur=0.5))
        await s.commit()
    assert await repo.spent_today() == pytest.approx(before + 0.75)
    assert await repo.spent_today(exclude_turn=turn) == pytest.approx(before + 0.5)
    async with db.sessionmaker()() as s:  # keep the test database's day total small
        await s.execute(update(db.LLMCall).where(db.LLMCall.chat_id == "c", db.LLMCall.role == "t").values(cost_eur=0))
        await s.commit()
