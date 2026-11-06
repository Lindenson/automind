"""Spec 008 end to end: "new Skoda Octavia 2.0 diesel" is asked the power over the sourced versions (with where it
stands, "choose for me" and "remove"), and "выбери сам" settles it without another identity question."""

import uuid

from automind.chat.dialog.graph import build_graph
from automind.chat.dialog.runner import ChatRunner
from automind.chat.infrastructure.persistence.repositories import MessageRepo
from tests.fakes.fake_llm import FakeLLM
from tests.fakes.fixture_search import FixtureSearch
from tests.integration.test_identify_ladder import Store

from .conftest import budget_factory, make_ports


def _ru(delta: dict) -> dict:
    return {"request": "compare", "language": "ru", "delta": delta}


async def test_octavia_diesel_power_asked_then_choose_for_me_settles(saver):
    llm = FakeLLM()
    llm.responders["asker"] = lambda s, u: "Понял: новая Skoda Octavia."
    llm.responders["reporter"] = lambda s, u: "Отчёт."
    car = {
        "request_text": "новая Skoda Octavia 2.0 дизель",
        "make": "Skoda",
        "model": "Octavia",
        "condition": "NEW",
        "constraints": {"engine_hint": {"displacement_l": 2.0, "fuel": "diesel", "evidence": "2.0 дизель"}},
    }
    llm.queue("interpreter", _ru({"add_cars": [car]}), _ru({}))
    ports = make_ports(llm=llm, search=FixtureSearch("empty"))
    ports.versions = Store()  # type: ignore[assignment]
    rn = ChatRunner(build_graph(saver, tools=[]), ports, budget_factory(), messages=MessageRepo())
    chat = str(uuid.uuid4())
    r1 = await rn.run_turn(chat, "Оцени новую Skoda Octavia 2.0 дизель")
    assert r1.action == "ASK", r1.reply_text
    assert "Skoda Octavia · Mk4 · дизель 2.0 · мощность: ?" in r1.reply_text
    assert "2.0 TDI 116 CV, 2.0 TDI 150 CV" in r1.reply_text and "RS" not in r1.reply_text
    chips = [x["label"] for b in r1.blocks if b.get("type") == "quick_replies" for x in b["items"]]
    assert chips[:2] == ["2.0 TDI 116 CV", "2.0 TDI 150 CV"] and "Выбери сам" in chips
    r2 = await rn.run_turn(chat, "Выбери сам")
    _, data, _ = await rn.ports.cases.latest(chat)
    c = data["cars"][0]
    assert c["variant_id"] and "116" in c["label"] and c["resolution"] in ("CONFIRMED", "AUTO_OK"), r2.reply_text
    assert "мощность: ?" not in r2.reply_text
