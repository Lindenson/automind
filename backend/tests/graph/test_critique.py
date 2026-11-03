"""spec 004 FR-021, SC-005: critique always leads to research or a reworked report, never only an apology."""

import pytest

from tests.fakes.fixture_search import FixtureSearch

from .test_research_flow import INTERPRET, llm_for_research, runner
from .test_research_flow import fresh_variant as fresh_variant  # noqa: F401  (fixture)

pytestmark = pytest.mark.usefixtures("fresh_variant")


async def test_critique_reworks_or_researches(saver, chat_id):
    llm = llm_for_research().queue("interpreter", INTERPRET)
    llm.responders["reporter"] = lambda s, u: "Report."
    rn = runner(saver, llm, FixtureSearch("racer"))
    r1 = await rn.run_turn(chat_id, "FixtureMake Racer for a race enthusiast")
    assert r1.action == "REPORT", r1.reply_text
    llm.queue("interpreter", {"request": "critique", "language": "en", "delta": {}})
    r2 = await rn.run_turn(chat_id, "this is bad and boring")
    assert r2.status == "DONE" and r2.action == "REPORT", (r2.action, r2.reply_text)
    assert r2.reply_text.startswith(("I went back to the sources", "Nothing new was found")), r2.reply_text
    reporter_calls = [c for c in llm.calls if c.role == "reporter"]
    assert "criticised" in reporter_calls[-1].user
    assert r2.blocks[0]["type"] == "verdict"
