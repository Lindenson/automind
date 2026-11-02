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


async def test_typed_continue_continues_and_reconnect_resends_the_question(saver, chat_id):
    """User report 2026-11-02: no buttons were shown and the typed "Continue" was taken as "stop"."""
    llm = llm_for_research().queue("interpreter", INTERPRET).queue("reporter", "Report.")
    rn = runner(saver, llm, max_llm_calls=4)
    w = await rn.run_turn(chat_id, "FixtureMake Racer for a race enthusiast")
    assert w.confirm["kind"] == "limit"
    # a reload: the open question is sent again although the client already saw its seq
    from automind.infrastructure.events import EventBus

    ev = await EventBus().current(chat_id, w.turn_id, "confirm_request")
    assert ev and ev["kind"] == "limit" and "seq" not in ev and ev["resent"]
    r = await rn.resume(chat_id, {"choice": "text", "text": "Continue"})
    while r.status == "WAITING_CONFIRMATION" and r.confirm["kind"] == "limit":
        r = await rn.resume(chat_id, {"choice": "text", "text": "продолжай"})
    assert r.status == "DONE" and r.action == "REPORT"
    jobs = await rn.ports.jobs.for_turn(r.turn_id)
    assert any(j.status == "DONE" for j in jobs if j.round == 0)  # the paused jobs were re-run


def test_yes_or_no():
    from automind.orchestration.phrases import yes_or_no

    for t in ("Continue", "go ahead", "да", "Продолжай!", "давай дальше", "sí, sigue"):
        assert yes_or_no(t) == "yes", t
    for t in ("stop", "нет", "хватит", "answer with what you have"):
        assert yes_or_no(t) == "no", t
    assert yes_or_no("compare it with the Mazda CX-5 instead") is None
