"""SSRF guard (spec 007 T058a): no private, loopback, link-local or metadata address, also after a redirect."""

import httpx
import pytest

from automind.acquisition.infrastructure.fetch import Fetcher, FetchPolicy, FetchRefused, public_ip

PAGE = "<html><head><title>T</title></head><body><p>" + "text " * 200 + "</p></body></html>"


def _fetcher(handler, host_ips=None):
    seen: list[str] = []

    def wrapped(req):
        seen.append(str(req.url))
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return handler(req)

    async def no_sleep(_: float) -> None:
        return None

    client = httpx.AsyncClient(transport=httpx.MockTransport(wrapped))
    f = Fetcher(FetchPolicy(min_interval_per_host_s=0.0), client, sleep=no_sleep, host_ips=host_ips)
    return f, seen


def _html(_req):
    return httpx.Response(200, headers={"content-type": "text/html"}, text=PAGE)


@pytest.mark.parametrize("addr", ["127.0.0.1", "10.1.2.3", "192.168.0.10", "172.16.5.5", "169.254.169.254",
                                  "::1", "fe80::1", "0.0.0.0", "::ffff:127.0.0.1"])  # fmt: skip
def test_local_addresses_are_not_public(addr):
    assert not public_ip(addr)


def test_public_addresses_are_public():
    assert public_ip("93.184.216.34") and public_ip("2606:2800:220:1:248:1893:25c8:1946")


@pytest.mark.parametrize("url", ["http://127.0.0.1/admin", "http://10.0.0.5/", "http://169.254.169.254/latest/",
                                 "http://[::1]/", "http://localhost:8000/api/health"])  # fmt: skip
async def test_literal_local_hosts_are_refused_without_a_request(url):
    f, seen = _fetcher(_html)
    with pytest.raises(FetchRefused, match="private or local"):
        await f.fetch(url)
    assert seen == []


async def test_a_name_resolving_inside_is_refused():
    async def ips(host):
        return ["10.0.0.7"] if host == "intranet.example.com" else ["93.184.216.34"]

    f, seen = _fetcher(_html, ips)
    with pytest.raises(FetchRefused):
        await f.fetch("https://intranet.example.com/page")
    assert seen == []
    doc = await f.fetch("https://www.example.com/page")
    assert doc.title == "T"


async def test_a_redirect_to_localhost_is_refused():
    def handler(req):
        if req.url.host == "www.example.com":
            return httpx.Response(302, headers={"location": "http://127.0.0.1:8000/api/health"})
        return _html(req)

    f, seen = _fetcher(handler)
    with pytest.raises(FetchRefused, match="private or local"):
        await f.fetch("https://www.example.com/go")
    assert not any("127.0.0.1" in u for u in seen)
