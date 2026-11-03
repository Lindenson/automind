"""Direct page fetch (constitution VIII, FR-022; research R8): pasted URLs and manufacturer pages.

Order of checks for every request: deny-list → robots.txt (cached per host) → per-host rate limit
→ request with timeout → content type and size limit. Classified-ads sites are never contacted.
Transient failures (429, 5xx, timeouts, connection errors) are retried a bounded number of times.
"""

from __future__ import annotations

import asyncio
import codecs
import ipaddress
import logging
import re
import socket
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

from automind.application.ports import WebDoc
from automind.domain.evidence import is_denied

log = logging.getLogger(__name__)

REDIRECT_STATUSES = (301, 302, 303, 307, 308)


class FetchRefused(RuntimeError):
    """The URL may not be fetched (deny-list, robots, type or size). `reason` explains why.

    `transient` is True when the refusal came from a failure that may go away (429 or 5xx after the
    retries were used up): the page store then remembers it only briefly.
    """

    def __init__(self, reason: str, *, transient: bool = False) -> None:
        super().__init__(reason)
        self.reason = reason
        self.transient = transient


HostIps = Callable[[str], Awaitable[list[str]]]


async def system_host_ips(host: str) -> list[str]:
    """Addresses the host resolves to (A and AAAA)."""
    infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return sorted({str(i[4][0]) for i in infos})


def public_ip(addr: str) -> bool:
    """Spec 007 T058a (SSRF): only global addresses; never loopback, private, link-local (169.254.169.254, the
    cloud metadata service), reserved, multicast or unspecified."""
    try:
        ip = ipaddress.ip_address(addr.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not (ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_multicast
                                 or ip.is_reserved or ip.is_unspecified)  # fmt: skip


def _literal_ip(host: str) -> str | None:
    h = host.strip("[]")
    try:
        ipaddress.ip_address(h.split("%", 1)[0])
    except ValueError:
        return None
    return h


def _retryable_status(status: int) -> bool:
    return status == 429 or 500 <= status <= 599


@dataclass
class FetchPolicy:
    timeout_s: float = 15.0
    max_bytes: int = 3_000_000
    min_interval_per_host_s: float = 2.0
    robots_cache_hours: float = 24.0
    user_agent: str = "AutoMindResearchBot/0.2"
    allowed_content_types: tuple[str, ...] = ("text/html", "application/pdf", "text/plain")
    max_concurrency_per_host: int = 2
    max_concurrency_total: int = 8
    max_redirects: int = 5
    retries: int = 2
    retry_backoff_s: tuple[float, ...] = (1.0, 3.0)
    retry_after_cap_s: float = 10.0

    @classmethod
    def from_config(cls, d: dict[str, Any]) -> FetchPolicy:
        return cls(
            timeout_s=float(d.get("timeout_s", 15)),
            max_bytes=int(d.get("max_bytes", 3_000_000)),
            min_interval_per_host_s=float(d.get("min_interval_per_host_s", 2.0)),
            robots_cache_hours=float(d.get("robots_cache_hours", 24)),
            user_agent=str(d.get("user_agent", cls.user_agent)),
            allowed_content_types=tuple(d.get("allowed_content_types", cls.allowed_content_types)),
            max_concurrency_per_host=int(d.get("max_concurrency_per_host", 2)),
            max_concurrency_total=int(d.get("max_concurrency_total", 8)),
            max_redirects=int(d.get("max_redirects", 5)),
            retries=int(d.get("retries", 2)),
            retry_backoff_s=tuple(float(x) for x in d.get("retry_backoff_s", cls.retry_backoff_s)),
            retry_after_cap_s=float(d.get("retry_after_cap_s", 10)),
        )

    def backoff(self, attempt: int, retry_after: str | None = None) -> float:
        """Seconds to wait before retry number `attempt` (0-based); Retry-After wins, capped."""
        ra = _retry_after_s(retry_after)
        if ra is not None:
            return min(ra, self.retry_after_cap_s)
        if not self.retry_backoff_s:
            return 0.0
        return self.retry_backoff_s[min(attempt, len(self.retry_backoff_s) - 1)]


def _retry_after_s(value: str | None) -> float | None:
    """Retry-After as seconds: delta-seconds or an HTTP date; None when absent or unreadable."""
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - datetime.now(UTC)).total_seconds())


# Browsers decode these labels as windows-1252 (WHATWG Encoding); Spanish sites rely on it (€, “ ”).
_AS_CP1252 = {"iso-8859-1", "latin-1", "latin1", "iso8859-1", "us-ascii", "ascii", "iso-8859-15"}
_META_CHARSET = re.compile(rb"""<meta[^>]+charset\s*=\s*["']?\s*([A-Za-z0-9_.:-]+)""", re.IGNORECASE)
SNIFF_BYTES = 4096


def _codec(label: str | None) -> str | None:
    """A Python codec name for a charset label, or None when the label is unknown."""
    if not label:
        return None
    label = label.strip().strip("\"'").lower()
    if label in _AS_CP1252 and label != "iso-8859-15":
        return "cp1252"
    try:
        return codecs.lookup(label).name
    except LookupError:
        return None


def decode_body(body: bytes, header_charset: str | None = None) -> str:
    """Bytes → text: header charset, else <meta charset>, else UTF-8, else detected (cp1252 at worst)."""
    enc = _codec(header_charset)
    if enc is None:
        m = _META_CHARSET.search(body[:SNIFF_BYTES])
        enc = _codec(m.group(1).decode("ascii", "ignore")) if m else None
    if enc is not None:
        if enc == "utf-8" and body.startswith(codecs.BOM_UTF8):
            enc = "utf-8-sig"
        return body.decode(enc, errors="replace")
    try:
        return body.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass
    try:
        from charset_normalizer import from_bytes  # noqa: PLC0415

        best = from_bytes(body).best()
        if best is not None:
            return str(best)
    except ImportError:  # pragma: no cover - charset_normalizer comes with httpx's usual stack
        pass
    return body.decode("cp1252", errors="replace")


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.title = ""
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in ("script", "style", "noscript", "svg"):
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag in ("p", "br", "tr", "li", "h1", "h2", "h3", "h4", "div", "td", "th"):
            self.parts.append("\n" if tag != "td" and tag != "th" else " | ")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "noscript", "svg") and self._skip:
            self._skip -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> tuple[str, str]:
    p = _Text()
    p.feed(html)
    text = re.sub(r"[ \t\r\f\v]+", " ", "".join(p.parts))
    text = re.sub(r"\n\s*\n+", "\n", text)
    return p.title.strip(), text.strip()


@dataclass(frozen=True)
class RawPage:
    url: str  # final URL after redirects
    content_type: str
    body: bytes
    encoding: str | None  # charset from the Content-Type header only; None when the header has none

    def text(self) -> str:
        return decode_body(self.body, self.encoding)


@dataclass
class Fetcher:
    """Policy-compliant HTTP fetch (constitution VIII; spec 003 R4).

    Every hop (including redirects) is checked against the deny-list and robots.txt. robots.txt 401/403
    means "disallow all"; its Crawl-delay is honoured on top of the configured per-host interval.
    robots.txt itself is fetched under the same rules: no deny-listed host, redirects followed by hand
    up to `max_redirects`. Transient failures of a GET are retried (`retries`, backoff, Retry-After),
    each attempt waiting its turn under the per-host rate limit. Refusals are counted per domain in
    `refusals` (operator view: share of 403/REFUSED by domain) and logged as `fetch.refused`.
    """

    policy: FetchPolicy = field(default_factory=FetchPolicy)
    client: httpx.AsyncClient | None = None
    max_chars: int = 14000
    _robots: dict[str, tuple[float, RobotFileParser | None, bool]] = field(default_factory=dict)
    _last: dict[str, float] = field(default_factory=dict)
    _locks: dict[str, asyncio.Lock] = field(default_factory=dict)
    _host_sem: dict[str, asyncio.Semaphore] = field(default_factory=dict)
    _total_sem: asyncio.Semaphore | None = None
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
    requests: dict[str, int] = field(default_factory=dict)
    refusals: dict[str, dict[str, int]] = field(default_factory=dict)
    # SSRF guard (T058a): the resolver of host addresses. None = the system resolver when this fetcher owns its
    # HTTP client; an injected client (tests) checks only literal IP hosts unless a resolver is given.
    host_ips: HostIps | None = None

    async def _public_host(self, url: str) -> bool:
        """Every address of the URL's host is public (checked on each hop, so a redirect cannot reach inside)."""
        host = (urlparse(url).hostname or "").lower()
        if not host:
            return False
        if host in ("localhost", "localhost.localdomain") or host.endswith(".localhost"):
            return False
        if (lit := _literal_ip(host)) is not None:
            return public_ip(lit)
        resolve = self.host_ips or (system_host_ips if self.client is None else None)
        if resolve is None:
            return True
        try:
            addrs = await resolve(host)
        except (OSError, UnicodeError):
            return False
        return bool(addrs) and all(public_ip(a) for a in addrs)

    def _refused(self, url: str, reason: str, status: int | None = None) -> FetchRefused:
        domain = urlparse(url).netloc.lower()
        kind = f"http_{status}" if status is not None else reason.split(" ")[0] if reason else "refused"
        by = self.refusals.setdefault(domain, {})
        by[kind] = by.get(kind, 0) + 1
        log.info("fetch.refused domain=%s status=%s reason=%s", domain, status, reason,
                 extra={"event": "fetch.refused", "domain": domain, "status": status, "reason": reason})  # fmt: skip
        return FetchRefused(reason, transient=status is not None and _retryable_status(status))

    def refusal_stats(self) -> dict[str, dict[str, float]]:
        """Per domain: requests sent, refusals and their share (an operator view of blocked sites)."""
        out: dict[str, dict[str, float]] = {}
        for domain in set(self.requests) | set(self.refusals):
            n_ref = sum(self.refusals.get(domain, {}).values())
            n_req = self.requests.get(domain, 0)
            out[domain] = {"requests": n_req, "refused": n_ref, "share": n_ref / n_req if n_req else 1.0}
        return out

    def _client(self) -> httpx.AsyncClient:
        if self.client is None:
            self.client = httpx.AsyncClient(
                timeout=self.policy.timeout_s,
                follow_redirects=False,
                headers={"User-Agent": self.policy.user_agent},
            )
        return self.client

    async def _robots_for(self, url: str) -> tuple[RobotFileParser | None, bool]:
        """(parser or None when there is no robots.txt, deny_all)."""
        u = urlparse(url)
        host = f"{u.scheme}://{u.netloc}"
        cached = self._robots.get(host)
        if cached is None or time.monotonic() - cached[0] > self.policy.robots_cache_hours * 3600:
            rp: RobotFileParser | None = None
            deny_all = False
            try:
                r = await self._get_robots(f"{host}/robots.txt")
                if r is None or r.status_code in (401, 403):
                    deny_all = True  # robots.txt forbidden or behind a denied host: the site disallows us
                elif r.status_code < 400:
                    rp = RobotFileParser()
                    rp.parse(r.text.splitlines())
            except httpx.HTTPError:
                rp = None
            cached = (time.monotonic(), rp, deny_all)
            self._robots[host] = cached
        return cached[1], cached[2]

    async def _get_robots(self, url: str) -> httpx.Response | None:
        """GET robots.txt following redirects by hand: each hop must be http(s) and not deny-listed.

        None when a hop leads to a denied host; too many redirects count as "no robots.txt" (RFC 9309).
        """
        current = url
        for _ in range(self.policy.max_redirects + 1):
            u = urlparse(current)
            if u.scheme not in ("http", "https") or not u.netloc or is_denied(current):
                return None
            if not await self._public_host(current):
                return None
            r = await self._client().get(current, follow_redirects=False)
            if r.status_code in REDIRECT_STATUSES and r.headers.get("location"):
                current = str(httpx.URL(current).join(r.headers["location"]))
                continue
            return r
        return httpx.Response(404)

    async def _robots_allows(self, url: str) -> bool:
        rp, deny_all = await self._robots_for(url)
        if deny_all:
            return False
        return True if rp is None else rp.can_fetch(self.policy.user_agent, url)

    async def _crawl_delay(self, url: str) -> float:
        rp, _ = await self._robots_for(url)
        if rp is None:
            return 0.0
        try:
            d = rp.crawl_delay(self.policy.user_agent)
        except Exception:  # noqa: BLE001 - malformed robots line
            return 0.0
        return float(d or 0)

    async def _wait_turn(self, host: str, crawl_delay: float = 0.0) -> None:
        lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:
            interval = max(self.policy.min_interval_per_host_s, crawl_delay)
            wait = self._last.get(host, 0) + interval - time.monotonic()
            if wait > 0:
                await self.sleep(wait)
            self._last[host] = time.monotonic()

    async def _check(self, url: str) -> None:
        u = urlparse(url)
        if u.scheme not in ("http", "https") or not u.netloc:
            raise FetchRefused("not an http(s) URL")
        if is_denied(url):
            raise self._refused(url, "site is on the deny-list (classifieds or automated access forbidden)")
        if not await self._public_host(url):
            raise self._refused(url, "private or local address (not fetched)")
        if not await self._robots_allows(url):
            raise self._refused(url, "disallowed by robots.txt")

    async def fetch_raw(self, url: str) -> RawPage:
        current = url
        for _ in range(self.policy.max_redirects + 1):
            await self._check(current)
            result = await self._get_with_retries(current)
            if isinstance(result, RawPage):
                return result
            current = result  # a redirect: the next hop is checked again
        raise self._refused(url, f"more than {self.policy.max_redirects} redirects")

    async def _get_with_retries(self, url: str) -> RawPage | str:
        """One hop: the page, or the redirect target. Retries 429/5xx/transport errors only."""
        attempt = 0
        while True:
            try:
                return await self._get_once(url)
            except _Retry as r:
                if attempt >= self.policy.retries:
                    if r.error is not None:
                        raise r.error from None
                    raise self._refused(url, f"HTTP {r.status}", r.status) from None
                delay = self.policy.backoff(attempt, r.retry_after)
            attempt += 1
            await self.sleep(delay)

    async def _get_once(self, url: str) -> RawPage | str:
        if self._total_sem is None:
            self._total_sem = asyncio.Semaphore(self.policy.max_concurrency_total)
        host = urlparse(url).netloc
        sem = self._host_sem.setdefault(host, asyncio.Semaphore(self.policy.max_concurrency_per_host))
        async with self._total_sem, sem:
            await self._wait_turn(host, await self._crawl_delay(url))
            domain = host.lower()
            self.requests[domain] = self.requests.get(domain, 0) + 1
            try:
                async with self._client().stream("GET", url) as r:
                    if r.status_code in REDIRECT_STATUSES and r.headers.get("location"):
                        return str(httpx.URL(url).join(r.headers["location"]))
                    if _retryable_status(r.status_code):
                        raise _Retry(status=r.status_code, retry_after=r.headers.get("retry-after"))
                    if r.status_code >= 400:
                        raise self._refused(url, f"HTTP {r.status_code}", r.status_code)
                    ctype = r.headers.get("content-type", "").split(";")[0].strip().lower()
                    if ctype not in self.policy.allowed_content_types:
                        raise self._refused(url, f"content type {ctype or 'unknown'} not allowed")
                    body = bytearray()
                    async for chunk in r.aiter_bytes():
                        body += chunk
                        if len(body) > self.policy.max_bytes:
                            raise self._refused(url, f"larger than {self.policy.max_bytes} bytes")
                    return RawPage(url=str(r.url), content_type=ctype, body=bytes(body), encoding=r.charset_encoding)
            except httpx.TransportError as e:  # timeouts, connect/read errors: worth another try
                raise _Retry(error=e) from e

    async def fetch(self, url: str) -> WebDoc:
        """Fetch and convert to plain text (pasted URLs; the page store does its own extraction)."""
        raw = await self.fetch_raw(url)
        if raw.content_type == "application/pdf":
            from automind.infrastructure.pages import pdf_text  # noqa: PLC0415

            return WebDoc(url=raw.url, title=url, text=pdf_text(raw.body)[: self.max_chars], snippet_only=False)
        text_ = raw.text()
        title, text = html_to_text(text_) if raw.content_type == "text/html" else ("", text_)
        return WebDoc(url=raw.url, title=title or url, text=text[: self.max_chars], snippet_only=False)

    async def aclose(self) -> None:
        if self.client is not None:
            await self.client.aclose()


class _Retry(Exception):  # noqa: N818 - internal control flow, not an error for callers
    def __init__(self, *, status: int | None = None, retry_after: str | None = None,
                 error: Exception | None = None) -> None:  # fmt: skip
        super().__init__(status or error)
        self.status = status
        self.retry_after = retry_after
        self.error = error
