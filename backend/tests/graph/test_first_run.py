"""Live chats 5821ac77 / d7edfc29 / 2f8b0018 ("replace my 10-year-old diesel Prado J150 with a new Sorento PHEV").

A. The first report of a chat reused cached research: an area an earlier run left below its minimum, without ever
   querying the registry's sources, was not searched again (the 12-hour retry window), so the report said
   "insufficient data" until the user pressed "find it". The first research of a turn now gives such an area a
   targeted round with the registry's `site:` queries and the escalation to the other European markets (spec 010
   FR-022); once they were tried, the area waits for the usual retry window (no repeated cost).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select, update

from automind.acquisition.registry.application.service import RegistryService
from automind.acquisition.registry.infrastructure.repo import RegistryRepo
from automind.infrastructure.config import favourite_queries, load_yaml
from automind.infrastructure.db import models as m
from automind.infrastructure.db.session import sessionmaker
from tests.fakes.fixture_search import FixtureSearch

from .conftest import make_ports, open_web_reference, share
from .test_research_flow import INTERPRET, MAKE, llm_for_research, runner
from .test_research_flow import fresh_variant as fresh_variant  # noqa: F401  (fixture)

TEXT = "FixtureMake Racer for a race enthusiast"
EARLIER = datetime(2026, 11, 1, 11, 0, tzinfo=UTC)  # an hour before the fixed clock: inside the 12-hour window


async def _registry_candidate() -> None:
    """A surveyed source for instrumented tests in another European market (FR): only the escalation queries it."""
    async with sessionmaker()() as s:
        for t in (m.RegistryAttempt, m.RegistryChange, m.TruthSignal, m.CapabilityRow, m.SourceRow):
            await s.execute(delete(t))
        s.add(m.SourceRow(domain="mesures.example", source_type="INSTRUMENTED_TEST", family="mesures.example",
                          markets=["FR"], access="ok"))  # fmt: skip
        await s.flush()
        s.add(m.CapabilityRow(domain="mesures.example", area="measured", market="FR", status="candidate"))
        await s.commit()


def _with_registry(rn) -> None:  # noqa: ANN001
    cfg = {**load_yaml("registry.yaml"), "autonomy": False}
    share(rn.ports, registry=RegistryService(RegistryRepo(cfg), cfg), ref=open_web_reference(
        favourite_queries={k: v for k, v in favourite_queries().items() if k.startswith("registry")}
    ))  # fmt: skip


async def _left_short(area: str) -> str:
    """An earlier chat's run of `area` stayed below its minimum an hour ago, without the registry's sources."""
    async with sessionmaker()() as s:
        vid = (await s.execute(select(m.Variant.id).where(m.Variant.make == MAKE))).scalar_one()
        await s.execute(
            update(m.ResearchRun)
            .where(m.ResearchRun.variant_id == vid, m.ResearchRun.area == area)
            .values(minimum_met=False, completed_at=EARLIER, registry_at=None)
        )
        await s.commit()
    return vid


async def test_first_report_retries_a_short_area_on_the_registry_sources_once(saver, fresh_variant):
    await _registry_candidate()
    llm = llm_for_research().queue("interpreter", INTERPRET).queue("reporter", "Report.")
    r1 = await runner(saver, llm, FixtureSearch("racer")).run_turn(str(uuid.uuid4()), TEXT)
    assert r1.action == "REPORT", r1.reply_text
    vid = await _left_short("measured")

    # another chat, the same car: its first report researches the short area again, on the registry's sources of
    # the other European markets (before: no job at all, "insufficient data" until "find it")
    llm2 = llm_for_research().queue("interpreter", INTERPRET).queue("reporter", "Report.")
    search = FixtureSearch("racer")
    rn = runner(saver, llm2, search)
    _with_registry(rn)
    r2 = await rn.run_turn(str(uuid.uuid4()), TEXT)
    assert r2.status == "DONE" and r2.action == "REPORT", (r2.action, r2.reply_text)
    jobs = await make_ports().jobs.for_turn(r2.turn_id)
    assert ("measured", 0) in {(j.area, j.round) for j in jobs}, [(j.area, j.round) for j in jobs]
    assert {j.area for j in jobs} == {"measured"}  # the met areas stay cached
    site = [(q, mk) for q, mk in zip(search.queries, search.markets, strict=True) if "site:mesures.example" in q]
    assert site and all(mk == "FR" for _, mk in site), search.queries
    async with sessionmaker()() as s:
        run = (
            await s.execute(
                select(m.ResearchRun).where(m.ResearchRun.variant_id == vid, m.ResearchRun.area == "measured")
            )  # fmt: skip
        ).scalar_one()
    assert run.registry_at is not None  # the registry's sources were tried for this area

    # still short, but the registry's sources were tried: a third chat waits for the retry window (no repeated cost)
    llm3 = llm_for_research().queue("interpreter", INTERPRET).queue("reporter", "Report.")
    rn3 = runner(saver, llm3, FixtureSearch("racer"))
    _with_registry(rn3)
    async with sessionmaker()() as s:
        await s.execute(update(m.ResearchRun).where(m.ResearchRun.variant_id == vid,
                                                    m.ResearchRun.area == "measured")
                        .values(minimum_met=False, completed_at=EARLIER))  # fmt: skip
        await s.commit()
    r3 = await rn3.run_turn(str(uuid.uuid4()), TEXT)
    assert await make_ports().jobs.for_turn(r3.turn_id) == [], r3.reply_text
