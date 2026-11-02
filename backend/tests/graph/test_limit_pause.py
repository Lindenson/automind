"""Limits pause research and ask the user instead of cancelling it (user feedback 2026-11-02)."""

import pytest

from automind.infrastructure.db.repositories import MessageRepo
from automind.orchestration.graph import build_graph
from automind.orchestration.runner import ChatRunner
from tests.fakes.fixture_search import FixtureSearch

from .conftest import budget_factory, make_ports
from .test_research_flow import INTERPRET, llm_for_research
from .test_research_flow import fresh_variant as fresh_variant  # noqa: F401  (fixture)

pytestmark = pytest.mark.usefixtures("fresh_variant")


def runner(saver, llm, **limits):
    ports = make_ports(llm=llm, search=FixtureSearch("racer"))
    return ChatRunner(build_graph(saver, tools=[]), ports, budget_factory(**limits), messages=MessageRepo())


async def test_limit_asks_and_continue_finishes_the_research(saver, chat_id):
    llm = llm_for_research().queue("interpreter", INTERPRET).queue("reporter", "Report.")
    rn = runner(saver, llm, max_llm_calls=4)
    w = await rn.run_turn(chat_id, "FixtureMake Racer for a race enthusiast")
    assert w.status == "WAITING_CONFIRMATION" and w.confirm["kind"] == "limit", (w.status, w.reply_text)
    assert [o["id"] for o in w.confirm["options"]] == ["continue", "stop"]
    left = int(w.confirm["text"].split("task(s) left")[0].split()[-1])
    assert left >= 1
    r = await rn.resume(chat_id, {"choice": "continue"})
    while r.status == "WAITING_CONFIRMATION" and r.confirm["kind"] == "limit":  # each "continue" adds one allowance
        r = await rn.resume(chat_id, {"choice": "continue"})
    assert r.status == "DONE" and r.action == "REPORT", (r.status, r.reply_text)


async def test_limit_stop_answers_with_what_exists(saver, chat_id):
    llm = llm_for_research().queue("interpreter", INTERPRET).queue("reporter", "Report from what exists.")
    rn = runner(saver, llm, max_llm_calls=4)
    w = await rn.run_turn(chat_id, "FixtureMake Racer for a race enthusiast")
    assert w.confirm["kind"] == "limit"
    r = await rn.resume(chat_id, {"choice": "stop"})
    assert r.status == "DONE" and r.action == "REPORT", (r.status, r.reply_text)
    assert "limit" not in r.reply_text.lower() or "stopped" not in r.reply_text.lower()
