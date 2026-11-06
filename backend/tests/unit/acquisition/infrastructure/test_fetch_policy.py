"""Fetch policy additions (spec 003 T015): Crawl-delay, robots 401/403, redirect re-check, per-host concurrency."""

import asyncio
import time

import httpx
import pytest

from automind.acquisition.infrastructure.fetch import Fetcher, FetchPolicy, FetchRefused

PAGE = "<html><head><title>T</title></head><body><p>" + "text " * 200 + "</p></body></html>"


def fetcher(handler, **policy):
    seen = []

    def wrapped(req):
        seen.append(str(req.url))
        return handler(req)

    p = FetchPolicy(**{"min_interval_per_host_s": 0.0, **policy})
    return Fetcher(p, httpx.AsyncClient(transport=httpx.MockTransport(wrapped))), seen


async def test_crawl_delay_from_robots_is_respected():
    def h(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nCrawl-delay: 1\n")
        return httpx.Response(200, html=PAGE)

    f, _ = fetcher(h)
    t0 = time.monotonic()
    await f.fetch_raw("https://slow.example/a")
    await f.fetch_raw("https://slow.example/b")
    assert time.monotonic() - t0 >= 0.95  # Python robotparser reads integer delays only


@pytest.mark.parametrize("status", [401, 403])
async def test_robots_forbidden_means_disallow_all(status):
    f, seen = fetcher(
        lambda req: httpx.Response(status) if req.url.path == "/robots.txt" else httpx.Response(200, html=PAGE)
    )
    with pytest.raises(FetchRefused, match="robots"):
        await f.fetch_raw("https://closed.example/page")
    assert seen == ["https://closed.example/robots.txt"]


async def test_robots_404_allows():
    f, _ = fetcher(lambda req: httpx.Response(404) if req.url.path == "/robots.txt" else httpx.Response(200, html=PAGE))
    raw = await f.fetch_raw("https://open.example/page")
    assert raw.content_type == "text/html" and b"text" in raw.body


async def test_redirect_to_denied_host_is_refused():
    def h(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(302, headers={"location": "https://www.milanuncios.com/coche"})

    f, seen = fetcher(h)
    with pytest.raises(FetchRefused, match="deny-list"):
        await f.fetch_raw("https://shortener.example/x")
    assert not any("milanuncios" in u for u in seen)


async def test_redirect_followed_and_final_url_kept():
    def h(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        if req.url.path == "/old":
            return httpx.Response(301, headers={"location": "/new"})
        return httpx.Response(200, html=PAGE)

    f, _ = fetcher(h)
    raw = await f.fetch_raw("https://site.example/old")
    assert raw.url == "https://site.example/new"


async def test_at_most_two_concurrent_requests_per_host():
    active = {"now": 0, "max": 0}

    class T(httpx.AsyncBaseTransport):
        async def handle_async_request(self, req):
            if req.url.path == "/robots.txt":
                return httpx.Response(404)
            active["now"] += 1
            active["max"] = max(active["max"], active["now"])
            await asyncio.sleep(0.05)
            active["now"] -= 1
            return httpx.Response(200, html=PAGE)

    f = Fetcher(FetchPolicy(min_interval_per_host_s=0.0), httpx.AsyncClient(transport=T()))
    await asyncio.gather(*(f.fetch_raw(f"https://busy.example/{i}") for i in range(6)))
    assert active["max"] == 2
