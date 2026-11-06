# ruff: noqa: E501
"""Spec 005 US4 (FR-016–FR-018): the incident's first message yields family, 12,000–24,000 km a year, the south of
Spain (hot climate) and ONE new-or-used question for both cars, asked together with the identity question."""

import uuid

from automind.chat.dialog.graph import build_graph
from automind.chat.dialog.runner import ChatRunner
from automind.chat.infrastructure.persistence.repositories import MessageRepo
from tests.fakes.fake_llm import FakeLLM
from tests.fakes.fixture_search import FixtureSearch

from .conftest import budget_factory, forget_make, make_ports
from .test_corrections import _seed_ateca

FIRST = ("скажи наскольо хороша byd - найди соотвествующу модель - в сравнеии с сеат атека... для долгосрочной "
         "семейной эксплуатации на юге испании.. нужно 1-2 тыс км в месяц. и по городу и за.")  # fmt: skip


async def test_incident_first_message_profile_and_one_condition_question(saver):
    await forget_make("BYD")
    await _seed_ateca()
    llm = FakeLLM()
    llm.responders["asker"] = lambda s, u: "Понял: BYD против SEAT Ateca для семьи."
    llm.queue("interpreter", {"request": "compare", "language": "ru", "delta": {
        "set_profile": {"family": "FAMILY", "evidence": {"family": "семейной"}}, "set_usage": ["CITY", "MOTORWAY", "FAMILY"],
        "add_cars": [{"request_text": "byd", "make": "BYD"}, {"request_text": "сеат атека", "make": "SEAT", "model": "Ateca"}]}})  # fmt: skip
    ports = make_ports(llm=llm, search=FixtureSearch("empty"))
    rn = ChatRunner(build_graph(saver, tools=[]), ports, budget_factory(), messages=MessageRepo())
    chat = str(uuid.uuid4())
    r = await rn.run_turn(chat, FIRST)
    assert r.action == "ASK", (r.action, r.reply_text)
    _, data, _ = await rn.ports.cases.latest(chat)
    p = data["profile"]
    assert (p["annual_km_min"], p["annual_km_max"], data["annual_km"]) == (12000, 24000, 18000)
    assert p["region_code"] == "SOUTH" and p["climate"] == "HOT"
    kinds = [i["kind"] for i in data["pending"]["items"]]
    assert kinds.count("CONDITION") == 1 and "MAKE_LINEUP" in kinds, kinds
    chips = [c["label"] for c in next(b for b in r.blocks if b["type"] == "quick_replies")["items"]]
    assert "Новые" in chips and "Подержанные" in chips
    # "новые" answers for both cars, by code
    llm.queue("interpreter", {"request": "compare", "language": "ru", "delta": {}})
    await rn.run_turn(chat, "Новые")
    _, data, _ = await rn.ports.cases.latest(chat)
    assert [c["condition"] for c in data["cars"]] == ["NEW", "NEW"]
