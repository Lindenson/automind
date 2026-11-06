# ruff: noqa: E501
"""Spec 005 US6 (FR-022, FR-023): while an intake question is pending, a reply is never answered by generic chat
(chat 5be54966: "BYD is Build Your Dream" got a greeting and an invented BYD Atto 3)."""

import uuid

from automind.chat.dialog.graph import build_graph
from automind.chat.dialog.runner import ChatRunner
from automind.chat.infrastructure.persistence.repositories import MessageRepo
from tests.fakes.fake_llm import FakeLLM
from tests.fakes.fixture_search import FixtureSearch

from .conftest import budget_factory, forget_make, make_ports


def _runner(saver, llm):
    ports = make_ports(llm=llm, search=FixtureSearch("empty"))
    return ChatRunner(build_graph(saver, tools=[]), ports, budget_factory(), messages=MessageRepo())


async def test_brand_explanation_while_a_question_is_pending_stays_in_the_intake(saver):
    await forget_make("BYD")
    llm = FakeLLM()
    llm.responders["asker"] = lambda s, u: "Понял: вы сравниваете машину для семьи."
    llm.queue("interpreter", {"request": "compare", "language": "ru",
                              "delta": {"add_cars": [{"request_text": "та китайская", "condition": "NEW"}]}})  # fmt: skip
    rn = _runner(saver, llm)
    chat = str(uuid.uuid4())
    r1 = await rn.run_turn(chat, "сравни ту китайскую")
    assert r1.action == "ASK"
    llm.queue("interpreter", {"request": "general_question", "language": "ru", "delta": {}})
    r2 = await rn.run_turn(chat, "BYD это компания Build your dream китайская представленная в европе")
    assert r2.action == "ASK", (r2.action, r2.reply_text)
    assert "general" not in llm.roles_called()
    assert "привет" not in r2.reply_text.lower() and "Atto" not in r2.reply_text
    _, data, _ = await rn.ports.cases.latest(chat)
    assert data["cars"][0]["make"] == "BYD"
    assert "BYD" in r2.reply_text


async def test_a_wrong_language_acknowledgement_is_dropped(saver):
    llm = FakeLLM()
    llm.responders["asker"] = lambda s, u: "I understood you want a car."
    llm.queue("interpreter", {"request": "compare", "language": "ru",
                              "delta": {"add_cars": [{"request_text": "что-то", "condition": "NEW"}]}})  # fmt: skip
    rn = _runner(saver, llm)
    r = await rn.run_turn(str(uuid.uuid4()), "сравни что-то")
    assert r.action == "ASK" and "I understood" not in r.reply_text
