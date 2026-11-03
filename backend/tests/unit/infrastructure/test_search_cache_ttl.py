"""Empty search results are cached briefly (spec 007 FR-021): 118 of 439 cached searches were empty and
blocked a new search for a week."""

from datetime import timedelta

from automind.infrastructure.search.cache import cache_ttl


def test_empty_result_gets_the_short_ttl():
    cfg = {"cache_ttl_days": {"default": 7, "price": 3}, "empty_result_ttl_hours": 6}
    assert cache_ttl(cfg, "reliability", empty=True) == timedelta(hours=6)
    assert cache_ttl(cfg, "reliability", empty=False) == timedelta(days=7)
    assert cache_ttl(cfg, "price", empty=False) == timedelta(days=3)


def test_default_short_ttl_when_not_configured():
    assert cache_ttl({}, None, empty=True) == timedelta(hours=6)
