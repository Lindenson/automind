"""Search v2 in a turn (spec 003 T022/T024): repeat research is served from the search cache, the fallback
provider takes over, both providers down still completes the turn, AI follow-up queries are code-checked."""

import uuid

import pytest
from sqlalchemy import delete, select

from automind.application.ports import SearchHit
from automind.application.usage import Prices
from automind.infrastructure.db import models as m
from automind.infrastructure.db.repositories import MessageRepo
from automind.infrastructure.db.session import sessionmaker
from automind.infrastructure.search import SearchUnavailable
from automind.infrastructure.search.cache import CachedSearcher
from automind.orchestration.graph import build_graph
from automind.orchestration.runner import ChatRunner
from tests.fakes.fixture_search import FixtureSearch

from .conftest import budget_factory, engine, make_ports
from .test_research_flow import INTERPRET, llm_for_research
from .test_research_flow import fresh_variant as fresh_variant  # noqa: F401  (fixture)

CFG = {"num": 10, "markets": {"ES": {"gl": "es", "hl": "es"}}, "cache_ttl_days": {"default": 7}}
PRICES = Prices(llm={}, default_llm=(1, 1), eur_per_credit=0.0074, credits={}, provider_query_eur={"fx": 0.001})


class FixtureProvider:
    """A provider over a fixture scenario (hits only); pages come from the same scenario."""

    def __init__(self, fx: FixtureSearch, name="fx", fail=False):
        self.fx, self.name, self.fail, self.calls = fx, name, fail, 0

    async def search(self, query, *, gl, hl, num=10):
        self.calls += 1
        if self.fail:
            raise SearchUnavailable("down")
        return [SearchHit(h.url, h.title, h.snippet, h.rank) for h in self.fx._hits(query)]


def _hits(self, query):
    return [SearchHit(r["url"], r.get("title", ""), "", i + 1) for i, r in enumerate(self._rows(query))]


FixtureSearch._hits = _hits  # test helper: hits without charging


async def _forget_research():
    """Make the car's data stale again (but keep the search cache), so the next turn researches."""
    async with sessionmaker()() as s:
        await s.execute(delete(m.ResearchRun).where(m.ResearchRun.variant_id.in_(
            select(m.Variant.id).where(m.Variant.make == "FixtureMake"))))  # fmt: skip
        await s.execute(delete(m.SearchCache).where(m.SearchCache.query.ilike("%fixturemake%")))
        await s.commit()


async def _search_rows(turn_id):
    async with sessionmaker()() as s:
        rows = (await s.execute(select(m.SearchCall).where(m.SearchCall.turn_id == turn_id))).scalars().all()
        return [(r.provider, r.cached) for r in rows]


def _runner(saver, llm, searcher, fx):
    ports = make_ports(llm=llm, search=searcher)
    engine(ports).pages = fx
    return ChatRunner(build_graph(saver, tools=[]), ports, budget_factory(), messages=MessageRepo())


@pytest.mark.usefixtures("fresh_variant")
async def test_repeat_research_in_a_new_chat_uses_only_the_cache(saver, monkeypatch):
    monkeypatch.setattr("automind.infrastructure.search.cache.prices", lambda: PRICES)
    await _forget_research()
    fx = FixtureSearch("racer")
    provider = FixtureProvider(fx)
    searcher = CachedSearcher([provider], CFG)
    llm = llm_for_research().queue("interpreter", INTERPRET).queue("reporter", "Report.")
    r1 = await _runner(saver, llm, searcher, fx).run_turn(str(uuid.uuid4()), "FixtureMake Racer for a race enthusiast")
    assert r1.status == "DONE" and r1.usage["search_calls"] > 0
    paid = provider.calls
    async with sessionmaker()() as s:  # stale again, but the search cache stays
        await s.execute(delete(m.ResearchRun).where(m.ResearchRun.variant_id.in_(
            select(m.Variant.id).where(m.Variant.make == "FixtureMake"))))  # fmt: skip
        await s.commit()
    llm.queue("interpreter", INTERPRET).queue("reporter", "Report again.")
    r2 = await _runner(saver, llm, searcher, fx).run_turn(str(uuid.uuid4()), "FixtureMake Racer for a race enthusiast")
    assert r2.status == "DONE"
    assert provider.calls == paid  # no paid search in the second chat (SC-006)
    rows = await _search_rows(r2.turn_id)
    assert rows and all(cached for _, cached in rows)
    assert r2.usage["search_calls"] == 0


@pytest.mark.usefixtures("fresh_variant")
async def test_fallback_provider_and_all_down(saver, monkeypatch):
    monkeypatch.setattr(
        "automind.infrastructure.search.cache.prices",
        lambda: Prices(
            llm={},
            default_llm=(1, 1),
            eur_per_credit=0.0074,
            credits={},
            provider_query_eur={"fx": 0.001, "backup": 0.002},
        ),  # fmt: skip
    )
    await _forget_research()
    fx = FixtureSearch("racer")
    primary, backup = FixtureProvider(fx, "fx", fail=True), FixtureProvider(fx, "backup")
    llm = llm_for_research().queue("interpreter", INTERPRET).queue("reporter", "Report.")
    r = await _runner(saver, llm, CachedSearcher([primary, backup], CFG), fx).run_turn(
        str(uuid.uuid4()), "FixtureMake Racer for a race enthusiast"
    )
    assert r.status == "DONE" and backup.calls > 0
    assert {p for p, _ in await _search_rows(r.turn_id)} == {"backup"}

    await _forget_research()
    llm.queue("interpreter", INTERPRET).queue("reporter", "Report with what exists.")
    down = CachedSearcher([FixtureProvider(fx, "fx", fail=True)], CFG)
    r2 = await _runner(saver, llm, down, fx).run_turn(str(uuid.uuid4()), "FixtureMake Racer for a race enthusiast")
    assert r2.status == "DONE"  # every search failed, the turn still completes (FR-023)
