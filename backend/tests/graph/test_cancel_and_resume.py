"""Cancel and restart during research (FR-043, FR-044, SC-013)."""

import asyncio
import contextlib

import pytest
from sqlalchemy import select

from automind.infrastructure.db import models as m
from automind.infrastructure.db.repositories import MessageRepo
from automind.infrastructure.db.session import sessionmaker
from automind.orchestration.graph import build_graph
from automind.orchestration.runner import ChatRunner
from tests.fakes.fixture_search import FixtureSearch

from .conftest import budget_factory, make_ports
from .test_research_flow import INTERPRET, fresh_variant, llm_for_research  # noqa: F401  (fixture)


class GatedSearch(FixtureSearch):
    """Review searches wait for a gate, so a test can stop the turn while research is running."""

    def __init__(self, scenario: str, gate: asyncio.Event) -> None:
        super().__init__(scenario)
        self.gate = gate

    async def search(self, query: str, max_results: int = 5):
        if "review" in query.lower():
            await self.gate.wait()
        return await super().search(query, max_results)


pytestmark = pytest.mark.usefixtures("fresh_variant")


def runner(saver, llm, search):
    ports = make_ports(llm=llm, search=search)
    return ChatRunner(build_graph(saver, tools=[]), ports, budget_factory(), messages=MessageRepo())


async def jobs_of(turn_id):
    async with sessionmaker()() as s:
        rows = (await s.execute(select(m.ResearchJob).where(m.ResearchJob.turn_id == turn_id))).scalars().all()
    return {(j.area, j.round): j for j in rows}


async def wait_for(cond, timeout=10.0):
    end = asyncio.get_running_loop().time() + timeout
    while not await cond():
        assert asyncio.get_running_loop().time() < end, "condition not reached"
        await asyncio.sleep(0.05)


async def test_cancel_mid_research_keeps_validated_data(saver, chat_id):
    gate = asyncio.Event()
    r = runner(saver, llm_for_research().queue("interpreter", INTERPRET), GatedSearch("racer", gate))
    task = asyncio.create_task(r.run_turn(chat_id, "FixtureMake Racer for a race enthusiast"))

    async def specs_done():
        turn = await make_ports().turns.active(chat_id)
        if turn is None:
            return False
        jobs = await jobs_of(turn.id)
        return jobs.get(("specs", 0)) is not None and jobs[("specs", 0)].status == "DONE"

    await wait_for(specs_done)
    turn = await make_ports().turns.active(chat_id)
    assert await r.cancel(chat_id)
    res = await task
    assert res.status == "CANCELLED"
    jobs = await jobs_of(turn.id)
    assert jobs[("specs", 0)].status == "DONE" and jobs[("reviews", 0)].status == "SKIPPED"
    async with sessionmaker()() as s:
        accepted = (
            (
                await s.execute(
                    select(m.Claim).where(
                        m.Claim.status == "ACCEPTED",
                        m.Claim.area == "specs",
                        m.Claim.variant_id == jobs[("specs", 0)].variant_id,
                    )
                )
            )
            .scalars()
            .all()
        )
    assert accepted  # validated data stays cached


async def test_restart_resumes_without_redoing_finished_jobs(saver, chat_id):
    gate = asyncio.Event()
    a = runner(saver, llm_for_research().queue("interpreter", INTERPRET), GatedSearch("racer", gate))

    async def crash(*_args):  # a killed process runs no cleanup
        return None

    a._finish_cancelled = crash  # type: ignore[method-assign]
    task = asyncio.create_task(a.run_turn(chat_id, "FixtureMake Racer for a race enthusiast"))

    async def two_done():
        turn = await make_ports().turns.active(chat_id)
        if turn is None:
            return False
        jobs = await jobs_of(turn.id)
        return sum(1 for j in jobs.values() if j.status == "DONE") >= 2

    await wait_for(two_done)
    turn = await make_ports().turns.active(chat_id)
    a._tasks[chat_id].cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    before = await jobs_of(turn.id)
    done_before = {k: j.attempts for k, j in before.items() if j.status == "DONE"}
    assert (await make_ports().turns.get(turn.id)).status == "RUNNING"  # left behind by the "crash"

    b = runner(saver, llm_for_research().queue("reporter", "Report after restart."), FixtureSearch("racer"))
    assert await b.resume_incomplete({chat_id}) == [turn.id]
    result = await b._tasks[chat_id]
    assert result.status == "DONE" and result.action == "REPORT"
    after = await jobs_of(turn.id)
    assert {k: after[k].attempts for k in done_before} == done_before  # finished jobs were not redone
    assert all(j.status == "DONE" for j in after.values())
