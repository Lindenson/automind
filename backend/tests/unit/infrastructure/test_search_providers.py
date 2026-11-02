"""Search providers parse their APIs into SearchHit and map errors to SearchUnavailable (spec 003 T018)."""

import json

import httpx
import pytest

from automind.infrastructure.search import SearchUnavailable
from automind.infrastructure.search.cache import cache_key, normalise_query
from automind.infrastructure.search.serpapi import SerpApiProvider
from automind.infrastructure.search.serper import SerperProvider

SERPER = {"organic": [{"title": "BMW Serie 5 520d", "link": "https://www.km77.com/x/datos", "snippet": "190 CV",
                       "position": 1}, {"title": "no link"}]}  # fmt: skip
SERPAPI = {"organic_results": [{"title": "BMW 520d", "link": "https://www.ultimatespecs.com/y", "snippet": "140 kW",
                                "position": 1}]}  # fmt: skip


def _transport(status, body, seen):
    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(status, json=body)

    return httpx.MockTransport(handler)


async def test_serper_parses_organic_and_sends_locale():
    seen = []
    p = SerperProvider(api_key="k", transport=_transport(200, SERPER, seen))
    hits = await p.search("bmw 520d site:km77.com", gl="es", hl="es")
    assert [(h.url, h.rank) for h in hits] == [("https://www.km77.com/x/datos", 1)]
    body = json.loads(seen[0].content)
    assert body == {"q": "bmw 520d site:km77.com", "gl": "es", "hl": "es", "num": 10}
    assert seen[0].headers["X-API-KEY"] == "k"


async def test_serpapi_parses_organic_results():
    seen = []
    p = SerpApiProvider(api_key="k", transport=_transport(200, SERPAPI, seen))
    hits = await p.search("bmw 520d", gl="gb", hl="en")
    assert hits[0].url == "https://www.ultimatespecs.com/y"
    assert seen[0].url.params["engine"] == "google" and seen[0].url.params["gl"] == "gb"


@pytest.mark.parametrize("status", [401, 402, 429, 500])
async def test_errors_mean_unavailable(status):
    p = SerperProvider(api_key="k", transport=_transport(status, {}, []))
    with pytest.raises(SearchUnavailable):
        await p.search("q", gl="es", hl="es")


async def test_missing_key_is_unavailable():
    with pytest.raises(SearchUnavailable):
        await SerperProvider(api_key="").search("q", gl="es", hl="es")


def test_query_normalisation_and_key():
    a = "BMW  520d site:km77.com OR site:auto-data.net"
    b = "bmw 520d site:auto-data.net OR site:km77.com"
    assert normalise_query(a) == normalise_query(b) == "bmw 520d site:auto-data.net OR site:km77.com"
    assert cache_key(a, "es", "es", 10) == cache_key(b, "es", "es", 10)
    assert cache_key(a, "es", "es", 10) != cache_key(a, "gb", "en", 10)
