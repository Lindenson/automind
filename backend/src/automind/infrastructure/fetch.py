"""Direct page fetch (constitution VIII, FR-022; research R8): pasted URLs and manufacturer pages.

Order of checks for every request: deny-list → robots.txt (cached per host) → per-host rate limit
→ request with timeout → content type and size limit. Classified-ads sites are never contacted.
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

from automind.application.ports import WebDoc
from automind.domain.evidence import is_denied


class FetchRefused(RuntimeError):
    """The URL may not be fetched (deny-list, robots, type or size). `reason` explains why."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


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
        )


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
    encoding: str | None


@dataclass
class Fetcher:
    """Policy-compliant HTTP fetch (constitution VIII; spec 003 R4).

    Every hop (including redirects) is checked against the deny-list and robots.txt. robots.txt 401/403
    means "disallow all"; its Crawl-delay is honoured on top of the configured per-host interval.
    """

    policy: FetchPolicy = field(default_factory=FetchPolicy)
    client: httpx.AsyncClient | None = None
    max_chars: int = 14000
    _robots: dict[str, tuple[float, RobotFileParser | None, bool]] = field(default_factory=dict)
    _last: dict[str, float] = field(default_factory=dict)
    _locks: dict[str, asyncio.Lock] = field(default_factory=dict)
    _host_sem: dict[str, asyncio.Semaphore] = field(default_factory=dict)
    _total_sem: asyncio.Semaphore | None = None

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
                r = await self._client().get(f"{host}/robots.txt", follow_redirects=True)
                if r.status_code in (401, 403):
                    deny_all = True  # access to robots.txt forbidden: treat the site as disallowing us
                elif r.status_code < 400:
                    rp = RobotFileParser()
                    rp.parse(r.text.splitlines())
            except httpx.HTTPError:
                rp = None
            cached = (time.monotonic(), rp, deny_all)
            self._robots[host] = cached
        return cached[1], cached[2]

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
                await asyncio.sleep(wait)
            self._last[host] = time.monotonic()

    async def _check(self, url: str) -> None:
        u = urlparse(url)
        if u.scheme not in ("http", "https") or not u.netloc:
            raise FetchRefused("not an http(s) URL")
        if is_denied(url):
            raise FetchRefused("site is on the deny-list (classifieds or automated access forbidden)")
        if not await self._robots_allows(url):
            raise FetchRefused("disallowed by robots.txt")

    async def fetch_raw(self, url: str) -> RawPage:
        if self._total_sem is None:
            self._total_sem = asyncio.Semaphore(self.policy.max_concurrency_total)
        current = url
        for _ in range(self.policy.max_redirects + 1):
            await self._check(current)
            host = urlparse(current).netloc
            sem = self._host_sem.setdefault(host, asyncio.Semaphore(self.policy.max_concurrency_per_host))
            async with self._total_sem, sem:
                await self._wait_turn(host, await self._crawl_delay(current))
                async with self._client().stream("GET", current) as r:
                    if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
                        current = str(httpx.URL(current).join(r.headers["location"]))
                        continue
                    if r.status_code >= 400:
                        raise FetchRefused(f"HTTP {r.status_code}")
                    ctype = r.headers.get("content-type", "").split(";")[0].strip().lower()
                    if ctype not in self.policy.allowed_content_types:
                        raise FetchRefused(f"content type {ctype or 'unknown'} not allowed")
                    body = bytearray()
                    async for chunk in r.aiter_bytes():
                        body += chunk
                        if len(body) > self.policy.max_bytes:
                            raise FetchRefused(f"larger than {self.policy.max_bytes} bytes")
                    return RawPage(url=str(r.url), content_type=ctype, body=bytes(body), encoding=r.encoding)
        raise FetchRefused(f"more than {self.policy.max_redirects} redirects")

    async def fetch(self, url: str) -> WebDoc:
        """Fetch and convert to plain text (pasted URLs; the page store does its own extraction)."""
        raw = await self.fetch_raw(url)
        if raw.content_type == "application/pdf":
            from automind.infrastructure.pages import pdf_text  # noqa: PLC0415

            return WebDoc(url=raw.url, title=url, text=pdf_text(raw.body)[: self.max_chars], snippet_only=False)
        text_ = raw.body.decode(raw.encoding or "utf-8", errors="replace")
        title, text = html_to_text(text_) if raw.content_type == "text/html" else ("", text_)
        return WebDoc(url=raw.url, title=title or url, text=text[: self.max_chars], snippet_only=False)

    async def aclose(self) -> None:
        if self.client is not None:
            await self.client.aclose()
