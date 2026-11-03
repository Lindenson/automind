"""Fetch hardening: charset sniffing, robots.txt under the fetch policy, bounded retries, refusal counts."""

import logging

import httpx
import pytest

from automind.infrastructure.fetch import Fetcher, FetchPolicy, FetchRefused, decode_body

SPANISH = "<p>Información técnica: consumo, tracción, año 2024, precio 35.000 €</p>"
PAGE = "<html><head><title>T</title></head><body><p>" + "text " * 200 + "</p></body></html>"


def fetcher(handler, **policy):
    seen: list[str] = []
    slept: list[float] = []

    def wrapped(req):
        seen.append(str(req.url))
        return handler(req)

    async def fake_sleep(s: float) -> None:
        slept.append(s)

    p = FetchPolicy(**{"min_interval_per_host_s": 0.0, **policy})
    f = Fetcher(p, httpx.AsyncClient(transport=httpx.MockTransport(wrapped)), sleep=fake_sleep)
    return f, seen, slept


def no_robots(page):
    return lambda req: httpx.Response(404) if req.url.path == "/robots.txt" else page(req)


# --- 4.9 encoding -------------------------------------------------------------------------------


def test_meta_charset_is_used_when_the_header_has_none():
    body = f'<html><head><meta charset="iso-8859-1"></head><body>{SPANISH}</body></html>'.encode("cp1252")
    assert SPANISH in decode_body(body, None)


def test_meta_http_equiv_charset():
    head = '<meta http-equiv="Content-Type" content="text/html; charset=windows-1252">'
    body = f"<html><head>{head}</head><body>{SPANISH}</body></html>".encode("cp1252")
    assert SPANISH in decode_body(body, None)


def test_undeclared_non_utf8_is_detected_not_mojibake():
    body = ("<html><body>" + SPANISH * 5 + "</body></html>").encode("cp1252")
    text = decode_body(body, None)
    assert "Información" in text and "Ã" not in text and "�" not in text


def test_utf8_without_declaration_and_bom():
    assert decode_body(SPANISH.encode("utf-8"), None) == SPANISH
    assert decode_body(b"\xef\xbb\xbf" + SPANISH.encode("utf-8"), None) == SPANISH


def test_header_charset_wins_over_meta_and_bad_header_falls_back():
    body = f'<meta charset="utf-8">{SPANISH}'.encode("cp1252")
    assert SPANISH in decode_body(body, "ISO-8859-1")  # header wins (latin-1 read as windows-1252)
    assert SPANISH in decode_body(f'<meta charset="windows-1252">{SPANISH}'.encode("cp1252"), "no-such-charset")


async def test_fetch_decodes_page_without_header_charset():
    body = f'<html><head><meta charset="windows-1252"><title>Año</title></head><body>{SPANISH}</body></html>'
    f, _, _ = fetcher(
        no_robots(lambda req: httpx.Response(200, content=body.encode("cp1252"), headers={"content-type": "text/html"}))
    )
    raw = await f.fetch_raw("https://es.example/a")
    assert raw.encoding is None and "precio 35.000 €" in raw.text()
    doc = await f.fetch("https://es.example/b")
    assert doc.title == "Año" and "tracción" in doc.text


# --- 4.11 robots.txt under the same policy ------------------------------------------------------


async def test_robots_redirect_to_denied_host_is_not_followed_and_disallows():
    def h(req):
        if req.url.path == "/robots.txt" and req.url.host == "mirror.example":
            return httpx.Response(301, headers={"location": "https://www.milanuncios.com/robots.txt"})
        return httpx.Response(200, html=PAGE)

    f, seen, _ = fetcher(h)
    with pytest.raises(FetchRefused, match="robots"):
        await f.fetch_raw("https://mirror.example/page")
    assert not any("milanuncios" in u for u in seen)
    assert seen == ["https://mirror.example/robots.txt"]


async def test_robots_redirects_are_followed_by_hand_and_bounded():
    def h(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(302, headers={"location": "/robots.txt?again"})
        if req.url.path == "/r2":
            return httpx.Response(200, text="User-agent: *\nDisallow: /private/\n")
        return httpx.Response(200, html=PAGE)

    f, seen, _ = fetcher(h, max_redirects=3)
    await f.fetch_raw("https://loop.example/page")  # too many redirects → treated as no robots.txt
    assert sum("robots.txt" in u for u in seen) == 4  # first request + 3 redirects, never unbounded

    def h2(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(301, headers={"location": "/r2"})
        return h(req)

    f2, _, _ = fetcher(h2)
    with pytest.raises(FetchRefused, match="robots"):
        await f2.fetch_raw("https://moved.example/private/x")


# --- 4.7 retries --------------------------------------------------------------------------------


async def test_503_is_retried_with_backoff_then_succeeds():
    calls = {"n": 0}

    def page(req):
        calls["n"] += 1
        return httpx.Response(503) if calls["n"] < 3 else httpx.Response(200, html=PAGE)

    f, _, slept = fetcher(no_robots(page))
    raw = await f.fetch_raw("https://flaky.example/a")
    assert b"text" in raw.body and calls["n"] == 3 and slept == [1.0, 3.0]


async def test_retry_after_is_honoured_and_capped():
    calls = {"n": 0}

    def page(req):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"retry-after": "4"})
        if calls["n"] == 2:
            return httpx.Response(429, headers={"retry-after": "3600"})
        return httpx.Response(200, html=PAGE)

    f, _, slept = fetcher(no_robots(page))
    await f.fetch_raw("https://busy.example/a")
    assert slept == [4.0, 10.0]


async def test_retries_exhausted_raise_a_transient_refusal():
    f, seen, slept = fetcher(no_robots(lambda req: httpx.Response(502)))
    with pytest.raises(FetchRefused, match="HTTP 502") as e:
        await f.fetch_raw("https://down.example/a")
    assert e.value.transient and len(slept) == 2
    assert seen.count("https://down.example/a") == 3


async def test_timeouts_are_retried_then_reraised():
    def page(req):
        raise httpx.ConnectTimeout("slow", request=req)

    f, seen, slept = fetcher(no_robots(page), retries=1)
    with pytest.raises(httpx.ConnectTimeout):
        await f.fetch_raw("https://slow.example/a")
    assert seen.count("https://slow.example/a") == 2 and slept == [1.0]


@pytest.mark.parametrize("status", [403, 404, 410])
async def test_other_4xx_are_not_retried(status):
    f, seen, slept = fetcher(no_robots(lambda req: httpx.Response(status)))
    with pytest.raises(FetchRefused, match=f"HTTP {status}") as e:
        await f.fetch_raw("https://gone.example/a")
    assert not e.value.transient and slept == [] and seen.count("https://gone.example/a") == 1


async def test_denied_and_robots_refused_are_not_retried():
    f, seen, slept = fetcher(lambda req: httpx.Response(200, text="User-agent: *\nDisallow: /\n"))
    with pytest.raises(FetchRefused, match="robots"):
        await f.fetch_raw("https://closed.example/a")
    with pytest.raises(FetchRefused, match="deny-list"):
        await f.fetch_raw("https://www.coches.net/x")
    assert slept == [] and seen == ["https://closed.example/robots.txt"]


async def test_retry_still_waits_its_turn_under_the_host_rate_limit():
    calls = {"n": 0}

    def page(req):
        calls["n"] += 1
        return httpx.Response(500) if calls["n"] == 1 else httpx.Response(200, html=PAGE)

    f, _, slept = fetcher(no_robots(page), min_interval_per_host_s=5.0, retry_backoff_s=(0.0,))
    await f.fetch_raw("https://rated.example/a")
    assert any(s > 4.0 for s in slept)  # the second attempt waited for the per-host interval


def test_retry_settings_from_config():
    p = FetchPolicy.from_config({"retries": 1, "retry_backoff_s": [2, 5], "retry_after_cap_s": 7})
    assert (p.retries, p.retry_backoff_s, p.retry_after_cap_s) == (1, (2.0, 5.0), 7.0)
    assert p.backoff(0) == 2.0 and p.backoff(5) == 5.0 and p.backoff(0, "100") == 7.0


# --- 4.8 refusals per domain --------------------------------------------------------------------


async def test_refusals_are_counted_per_domain_and_logged(caplog):
    def h(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(403) if req.url.path == "/blocked" else httpx.Response(200, html=PAGE)

    f, _, _ = fetcher(h)
    with caplog.at_level(logging.INFO, logger="automind.infrastructure.fetch"):
        await f.fetch_raw("https://site.example/ok")
        with pytest.raises(FetchRefused):
            await f.fetch_raw("https://site.example/blocked")
    assert f.refusals == {"site.example": {"http_403": 1}}
    assert f.refusal_stats()["site.example"] == {"requests": 2, "refused": 1, "share": 0.5}
    rec = next(r for r in caplog.records if getattr(r, "event", None) == "fetch.refused")
    assert rec.domain == "site.example" and rec.status == 403
