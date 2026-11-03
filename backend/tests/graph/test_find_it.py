"""spec 004 FR-015: "find it" researches only the named areas, without an interpretation call."""

import pytest

from tests.fakes.fixture_search import FixtureSearch

from .test_research_flow import INTERPRET, llm_for_research, runner
from .test_research_flow import fresh_variant as fresh_variant  # noqa: F401  (fixture)

pytestmark = pytest.mark.usefixtures("fresh_variant")


async def test_find_it_researches_the_named_areas_only(saver, chat_id):
    llm = llm_for_research().queue("interpreter", INTERPRET)
    llm.responders["reporter"] = lambda s, u: "Report."
    rn = runner(saver, llm, FixtureSearch("racer"))
    r1 = await rn.run_turn(chat_id, "FixtureMake Racer for a race enthusiast")
    assert r1.status == "DONE" and r1.action == "REPORT", r1.reply_text
    panel = next(b for b in r1.blocks if b["type"] == "data_panel")
    assert panel["cars"][0]["car_key"] == "car#1"
    calls = len(llm.roles_called())
    r2 = await rn.run_turn(chat_id, "Find the missing data: price", preset={"kind": "research_more",
                           "focus_cars": ["car#1"], "areas": ["price"]})  # fmt: skip
    assert r2.status == "DONE" and r2.action == "REPORT", (r2.action, r2.reply_text)
    assert "interpreter" not in llm.roles_called()[calls:]
    jobs = await rn.ports.jobs.for_turn(r2.turn_id)
    assert {j.area for j in jobs} == {"price"}
    assert r2.blocks[0]["type"] == "verdict"
