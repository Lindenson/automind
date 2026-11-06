"""Cache-first Searcher on the real DB (spec 003 T014/T019; SC-006)."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select

from automind.application.usage import Limits, Prices, TurnBudget, current_budget
from automind.infrastructure import db
from automind.infrastructure.search import SearchUnavailable
from automind.infrastructure.search.cache import CachedSearcher, cache_key
from automind.shared.contracts.web import SearchHit

CFG = {"num": 10, "markets": {"ES": {"gl": "es", "hl": "es"}}, "cache_ttl_days": {"default": 7, "price": 3}}
PRICES = Prices(llm={}, default_llm=(1, 1), eur_per_credit=0.0074, credits={"search_advanced": 2},
                provider_query_eur={"fake": 0.001, "backup": 0.002})  # fmt: skip


class Fake:
    def __init__(self, name, hits=None, fail=False):
        self.name, self.hits, self.fail, self.calls = name, hits or [], fail, 0

    async def search(self, query, *, gl, hl, num=10):
        self.calls += 1
        if self.fail:
            raise SearchUnavailable("down")
        return self.hits


HITS = [SearchHit("https://www.km77.com/a", "A", "s", 1), SearchHit("https://www.milanuncios.com/x", "ad", "s", 2)]


@pytest.fixture
async def clean(monkeypatch):
    await db.init_db()
    monkeypatch.setattr("automind.infrastructure.search.cache.prices", lambda: PRICES)
    async with db.sessionmaker()() as s:
        await s.execute(delete(db.SearchCache).where(db.SearchCache.query.like("cachetest%")))
        await s.execute(delete(db.SearchCall).where(db.SearchCall.turn_id == "cachetest-turn"))
        await s.commit()
    budget = TurnBudget(chat_id="cachetest", turn_id="cachetest-turn", prices=PRICES, limits=Limits())
    token = current_budget.set(budget)
    yield budget
    current_budget.reset(token)


async def _calls():
    async with db.sessionmaker()() as s:
        rows = (await s.execute(select(db.SearchCall).where(db.SearchCall.turn_id == "cachetest-turn"))).scalars()
        return [(r.provider, r.cached, float(r.cost_eur)) for r in rows]


async def test_second_identical_query_is_a_free_cache_hit(clean):
    p = Fake("fake", HITS)
    s = CachedSearcher([p], CFG)
    first = await s.search("cachetest bmw 520d", market="ES", area="specs")
    second = await s.search("CacheTest  BMW 520d", market="ES", area="specs")
    assert p.calls == 1
    assert [h.url for h in first] == [h.url for h in second] == ["https://www.km77.com/a"]  # deny-list dropped
    assert sorted(await _calls()) == [("fake", False, 0.001), ("fake", True, 0.0)]
    assert clean.search_calls == 1 and abs(clean.cost_eur - 0.001) < 1e-9


async def test_expired_entry_is_refetched(clean):
    p = Fake("fake", HITS)
    s = CachedSearcher([p], CFG)
    await s.search("cachetest expired", area="price")
    async with db.sessionmaker()() as sess:
        row = await sess.get(db.SearchCache, cache_key("cachetest expired", "es", "es", 10))
        assert row.expires_at - row.fetched_at == timedelta(days=3)  # price TTL
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await sess.commit()
    await s.search("cachetest expired", area="price")
    assert p.calls == 2


async def test_fallback_used_when_primary_fails_and_error_when_all_fail(clean):
    primary, backup = Fake("fake", fail=True), Fake("backup", HITS)
    hits = await CachedSearcher([primary, backup], CFG).search("cachetest fallback")
    assert hits and primary.calls == 1 and backup.calls == 1
    assert ("backup", False, 0.002) in await _calls()
    with pytest.raises(SearchUnavailable):
        await CachedSearcher([Fake("fake", fail=True)], CFG).search("cachetest all fail")
