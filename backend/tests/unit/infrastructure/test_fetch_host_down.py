"""A host that times out again and again is skipped for a while (live chat 48c8ac65: bmw.es ate a whole job)."""

import httpx
import pytest

from automind.infrastructure.fetch import HOST_DOWN_S, Fetcher, FetchPolicy, FetchRefused

PAGE = "<html><head><title>T</title></head><body><p>" + "text " * 200 + "</p></body></html>"


def _fetcher():
    seen: list[str] = []
    now = [0.0]

    def handler(req):
        seen.append(str(req.url))
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        if req.url.host == "www.slow.example":
            raise httpx.ReadTimeout("read timed out", request=req)
        return httpx.Response(200, headers={"content-type": "text/html"}, text=PAGE)

    async def no_sleep(_: float) -> None:
        return None

    async def ips(_host):
        return ["93.184.216.34"]

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    f = Fetcher(FetchPolicy(min_interval_per_host_s=0.0), client, sleep=no_sleep, host_ips=ips,
                clock=lambda: now[0])  # fmt: skip
    return f, seen, now


async def test_after_two_timeouts_the_host_is_skipped_then_tried_again_later():
    f, seen, now = _fetcher()
    with pytest.raises((FetchRefused, httpx.TimeoutException)):
        await f.fetch("https://www.slow.example/a")
    pages = [u for u in seen if "/robots.txt" not in u]
    assert len(pages) == 2  # the second timeout in a row stops the retries
    with pytest.raises(FetchRefused, match="not responding"):
        await f.fetch("https://www.slow.example/b")
    assert [u for u in seen if "/robots.txt" not in u] == pages  # no request at all
    assert (await f.fetch("https://www.ok.example/page")).title == "T"  # other hosts are not affected
    now[0] += HOST_DOWN_S + 1
    with pytest.raises((FetchRefused, httpx.TimeoutException)):
        await f.fetch("https://www.slow.example/c")
    assert any(u.endswith("/c") for u in seen)  # tried again after the pause
