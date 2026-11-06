"""US3 in a turn (spec 003 T045/T047): an infeasible budget gets an explicit verdict before any report; the
user chooses to see the report, to look at used cars, or alternatives; an unclear new/used budget is asked."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from automind.chat.dialog.graph import build_graph
from automind.chat.dialog.runner import ChatRunner
from automind.chat.infrastructure.persistence.repositories import MessageRepo
from automind.shared.infrastructure.db import models as m
from automind.shared.infrastructure.db.session import sessionmaker
from tests.fakes.fake_llm import FakeLLM
from tests.fakes.fixture_search import FixtureSearch

from .conftest import budget_factory, make_ports
from .test_research_flow import MAKE
from .test_research_flow import fresh_variant as fresh_variant  # noqa: F401  (fixture)

pytestmark = pytest.mark.usefixtures("fresh_variant")
FRESH = datetime(2026, 10, 30, tzinfo=UTC)
AREAS = ("specs", "price", "maintenance", "reliability", "reviews", "measured", "used_price", "used_issues")


def interpret(budget: dict, condition: str = "NEW") -> dict:
    return {
        "request": "compare",
        "language": "en",
        "persona_evidence": "I just want a sensible buy",
        "constraints_evidence": ["25000"],
        "delta": {
            "set_persona": {"persona": "BUYER", "source": "INFERRED"},
            "set_budget": budget,
            "add_cars": [{"request_text": "FixtureMake Racer", "make": MAKE, "model": "Racer", "condition": condition}],
        },
    }


async def _seed_cached_racer(price: float = 45000):
    """Make the fixture car fully researched: validated values and fresh research runs for every area."""
    async with sessionmaker()() as s:
        v = (await s.execute(select(m.Variant).where(m.Variant.make == MAKE))).scalar_one()
        v.vehicle_class = "compact"
        for attr, val in (("official_price_es", price), ("seats", 5), ("boot_volume", 380), ("max_power", 206),
                          ("curb_mass", 1480)):  # fmt: skip
            s.add(m.SpecValue(variant_id=v.id, attribute=attr, available=True, value_num=val, provenance="SOURCED",
                              confidence="HIGH", claim_ids=[]))  # fmt: skip
        for area in AREAS:
            s.add(m.ResearchRun(variant_id=v.id, area=area, completed_at=FRESH, minimum_met=True))
        await s.commit()


def _runner(saver, llm):
    ports = make_ports(llm=llm, search=FixtureSearch("empty"))
    return ChatRunner(build_graph(saver, tools=[]), ports, budget_factory(), messages=MessageRepo())


async def test_over_budget_new_car_gets_a_verdict_before_the_report(saver):
    await _seed_cached_racer()
    llm = FakeLLM().queue("interpreter", interpret({"max_eur": 25000, "intent": "NEW"}))
    llm.queue("reporter", "Report with the verdict.")
    rn = _runner(saver, llm)
    chat = str(uuid.uuid4())
    w = await rn.run_turn(chat, "A new FixtureMake Racer for 25000 euros?")
    assert w.status == "WAITING_CONFIRMATION" and w.confirm["kind"] == "feasibility", (w.status, w.reply_text)
    assert "45,000" in w.confirm["text"] and "25,000" in w.confirm["text"]
    assert [o["id"] for o in w.confirm["options"]] == ["report", "used", "alternatives"]  # spec US3 #1
    assert w.usage["search_calls"] == 0
    r = await rn.resume(chat, {"choice": "report"})
    assert r.status == "DONE" and r.action == "REPORT"
    fz = next(b for b in r.blocks if b["type"] == "feasibility")
    budget = fz["cars"][0]["checks"][0]
    assert budget["check"] == "BUDGET" and budget["verdict"] == "DOES_NOT_FIT"
    async with sessionmaker()() as s:
        rows = (await s.execute(select(m.FeasibilityCheck).where(m.FeasibilityCheck.chat_id == chat))).scalars().all()
    assert [x.verdict for x in rows] == ["DOES_NOT_FIT"]
    # the same request again: the answered verdict is not asked again
    llm.queue("interpreter", {"request": "follow_up_question", "language": "en", "delta": {}})
    llm.queue("answerer", "From what we have.")
    r2 = await rn.run_turn(chat, "and which is more reliable?")
    assert r2.status == "DONE" and r2.action != "FEASIBILITY"


async def test_any_intent_offers_used_with_an_age_range(saver):
    await _seed_cached_racer()
    llm = FakeLLM().queue("interpreter", interpret({"max_eur": 25000, "intent": "ANY"}))
    rn = _runner(saver, llm)
    w = await rn.run_turn(str(uuid.uuid4()), "FixtureMake Racer, I have 25000, new or used")
    assert w.confirm["kind"] == "feasibility"
    assert "used" in [o["id"] for o in w.confirm["options"]]
    assert "years old" in w.confirm["text"]  # the labelled depreciation estimate


async def test_unclear_new_or_used_budget_is_asked_first(saver):
    await _seed_cached_racer()
    llm = FakeLLM().queue("interpreter", interpret({"max_eur": 25000}, condition="UNKNOWN"))
    llm.queue("asker", "New or used?")
    r = await _runner(saver, llm).run_turn(str(uuid.uuid4()), "FixtureMake Racer for 25000?")
    assert r.status == "DONE" and r.action == "ASK", (r.action, r.reply_text)
    assert r.usage["search_calls"] == 0


async def test_budget_that_fits_goes_straight_to_the_report(saver):
    await _seed_cached_racer(price=24000)
    llm = FakeLLM().queue("interpreter", interpret({"max_eur": 25000, "intent": "NEW"})).queue("reporter", "Report.")
    r = await _runner(saver, llm).run_turn(str(uuid.uuid4()), "A new FixtureMake Racer for 25000?")
    assert r.status == "DONE" and r.action == "REPORT"
    fz = next(b for b in r.blocks if b["type"] == "feasibility")
    assert fz["cars"][0]["checks"][0]["verdict"] == "FITS"


async def test_alternatives_and_used_choices(saver):
    await _seed_cached_racer()
    llm = FakeLLM().queue("interpreter", interpret({"max_eur": 25000, "intent": "NEW"}))
    llm.queue("general", "Suggestions: a compact hatchback such as … (to research next).")
    rn = _runner(saver, llm)
    chat = str(uuid.uuid4())
    await rn.run_turn(chat, "A new FixtureMake Racer for 25000 euros?")
    r = await rn.resume(chat, {"choice": "alternatives"})
    assert r.status == "DONE" and "Suggestions" in r.reply_text
    assert any(b["type"] == "feasibility" for b in r.blocks)

    chat2 = str(uuid.uuid4())
    llm.queue("interpreter", interpret({"max_eur": 25000, "intent": "NEW"}))
    llm.queue("asker", "How old roughly?").queue("reporter", "Report.")
    await rn.run_turn(chat2, "A new FixtureMake Racer for 25000 euros?")
    r2 = await rn.resume(chat2, {"choice": "used"})
    assert r2.status in ("DONE", "WAITING_CONFIRMATION"), r2.reply_text
    _, data, _ = await rn.ports.cases.latest(chat2)
    assert data["budget"]["intent"] == "USED" and data["cars"][0]["condition"] == "USED"
