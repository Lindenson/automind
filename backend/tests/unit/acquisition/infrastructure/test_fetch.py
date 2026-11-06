"""Direct fetch policy (constitution VIII, FR-022): deny-list, robots.txt, limits."""

import time

import httpx
import pytest

from automind.acquisition.infrastructure.fetch import Fetcher, FetchPolicy, FetchRefused

PAGE = "<html><head><title>Prado 150</title><script>x=1</script></head><body><p>Power: 173 PS</p></body></html>"


def make(handler, **policy):
    seen = []

    def wrapped(req: httpx.Request):
        seen.append(str(req.url))
        return handler(req)

    f = Fetcher(
        FetchPolicy(**{"min_interval_per_host_s": 0.0, **policy}),
        httpx.AsyncClient(transport=httpx.MockTransport(wrapped)),
    )
    return f, seen


def ok(req):
    if req.url.path == "/robots.txt":
        return httpx.Response(200, text="User-agent: *\nDisallow: /private/\n")
    return httpx.Response(200, html=PAGE)


async def test_fetches_and_extracts_text():
    f, _ = make(ok)
    doc = await f.fetch("https://www.toyota.es/prado")
    assert doc.title == "Prado 150" and "Power: 173 PS" in doc.text and "x=1" not in doc.text


async def test_deny_listed_host_is_never_requested():
    f, seen = make(ok)
    with pytest.raises(FetchRefused, match="deny-list"):
        await f.fetch("https://www.coches.net/toyota-land-cruiser")
    assert seen == []


async def test_robots_disallow_and_cache():
    f, seen = make(ok)
    with pytest.raises(FetchRefused, match="robots"):
        await f.fetch("https://example.com/private/page")
    await f.fetch("https://example.com/public")
    assert seen.count("https://example.com/robots.txt") == 1


async def test_size_and_content_type_limits():
    big = lambda req: httpx.Response(200, html="x" * 5000) if req.url.path != "/robots.txt" else httpx.Response(404)  # noqa: E731
    f, _ = make(big, max_bytes=1000)
    with pytest.raises(FetchRefused, match="larger"):
        await f.fetch("https://a.com/big")
    img = lambda req: httpx.Response(200, content=b"\x89PNG", headers={"content-type": "image/png"})  # noqa: E731
    f2, _ = make(img)
    with pytest.raises(FetchRefused, match="content type"):
        await f2.fetch("https://a.com/x.png")


async def test_rate_limit_per_host():
    f, _ = make(ok, min_interval_per_host_s=0.3)
    t0 = time.monotonic()
    await f.fetch("https://a.com/1")
    await f.fetch("https://a.com/2")
    assert time.monotonic() - t0 >= 0.3
