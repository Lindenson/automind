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

    @classmethod
    def from_config(cls, d: dict[str, Any]) -> FetchPolicy:
        return cls(
            timeout_s=float(d.get("timeout_s", 15)),
            max_bytes=int(d.get("max_bytes", 3_000_000)),
            min_interval_per_host_s=float(d.get("min_interval_per_host_s", 2.0)),
            robots_cache_hours=float(d.get("robots_cache_hours", 24)),
            user_agent=str(d.get("user_agent", cls.user_agent)),
            allowed_content_types=tuple(d.get("allowed_content_types", cls.allowed_content_types)),
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


@dataclass
class Fetcher:
    policy: FetchPolicy = field(default_factory=FetchPolicy)
    client: httpx.AsyncClient | None = None
    max_chars: int = 14000
    _robots: dict[str, tuple[float, RobotFileParser | None]] = field(default_factory=dict)
    _last: dict[str, float] = field(default_factory=dict)
    _locks: dict[str, asyncio.Lock] = field(default_factory=dict)

    def _client(self) -> httpx.AsyncClient:
        if self.client is None:
            self.client = httpx.AsyncClient(
                timeout=self.policy.timeout_s,
                follow_redirects=True,
                headers={"User-Agent": self.policy.user_agent},
            )
        return self.client

    async def _robots_allows(self, url: str) -> bool:
        u = urlparse(url)
        host = f"{u.scheme}://{u.netloc}"
        cached = self._robots.get(host)
        if cached is None or time.monotonic() - cached[0] > self.policy.robots_cache_hours * 3600:
            rp: RobotFileParser | None = RobotFileParser()
            try:
                r = await self._client().get(f"{host}/robots.txt")
                if r.status_code >= 400:
                    rp = None  # no robots.txt: allowed
                else:
                    assert rp is not None
                    rp.parse(r.text.splitlines())
            except httpx.HTTPError:
                rp = None
            cached = (time.monotonic(), rp)
            self._robots[host] = cached
        rp = cached[1]
        return True if rp is None else rp.can_fetch(self.policy.user_agent, url)

    async def _wait_turn(self, host: str) -> None:
        lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:
            wait = self._last.get(host, 0) + self.policy.min_interval_per_host_s - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._last[host] = time.monotonic()

    async def fetch(self, url: str) -> WebDoc:
        u = urlparse(url)
        if u.scheme not in ("http", "https") or not u.netloc:
            raise FetchRefused("not an http(s) URL")
        if is_denied(url):
            raise FetchRefused("site is on the deny-list (classifieds or automated access forbidden)")
        if not await self._robots_allows(url):
            raise FetchRefused("disallowed by robots.txt")
        await self._wait_turn(u.netloc)
        async with self._client().stream("GET", url) as r:
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
        if ctype == "application/pdf":
            raise FetchRefused("PDF text extraction not available yet")
        raw = body.decode(r.encoding or "utf-8", errors="replace")
        title, text = html_to_text(raw) if ctype == "text/html" else ("", raw)
        return WebDoc(url=str(r.url), title=title or url, text=text[: self.max_chars], snippet_only=False)

    async def aclose(self) -> None:
        if self.client is not None:
            await self.client.aclose()
