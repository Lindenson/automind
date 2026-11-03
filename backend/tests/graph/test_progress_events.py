"""spec 004 FR-023: research emits a car × area progress grid that ends in a final state for every cell."""

import pytest
from sqlalchemy import select

from automind.infrastructure.db import models as m
from automind.infrastructure.db.session import sessionmaker
from tests.fakes.fixture_search import FixtureSearch

from .test_research_flow import INTERPRET, llm_for_research, runner
from .test_research_flow import fresh_variant as fresh_variant  # noqa: F401  (fixture)

pytestmark = pytest.mark.usefixtures("fresh_variant")


async def test_every_cell_is_queued_then_final(saver, chat_id):
    llm = llm_for_research().queue("interpreter", INTERPRET)
    llm.responders["reporter"] = lambda s, u: "Report."
    r = await runner(saver, llm, FixtureSearch("racer")).run_turn(chat_id, "FixtureMake Racer for a race enthusiast")
    assert r.action == "REPORT"
    async with sessionmaker()() as s:
        rows = (await s.execute(select(m.TurnEvent).where(m.TurnEvent.turn_id == r.turn_id,
                                                          m.TurnEvent.type == "progress"))).scalars().all()  # fmt: skip
    cells: dict[tuple[str, str, int], list[str]] = {}
    for e in sorted(rows, key=lambda e: e.seq):
        p = e.payload
        cells.setdefault((p["car_key"], p["area"], p["round"]), []).append(p["state"])
    assert cells and all(states[0] == "queued" for states in cells.values())
    assert all(states[-1] in ("done", "partial", "failed", "paused") for states in cells.values())
