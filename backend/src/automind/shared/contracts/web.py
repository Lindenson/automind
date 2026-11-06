"""Web documents, search hits and the page store: what search and fetching return, for the engine and the chat."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass
class WebDoc:
    url: str
    title: str
    text: str
    snippet_only: bool
    snapshot_id: str | None = None  # spec 011: the stored raw page this text came from


@dataclass(frozen=True)
class SearchHit:
    """One web search result. Never carries page text: pages come from the PageStore (spec 003 R1)."""

    url: str
    title: str
    snippet: str
    rank: int


class SearchProvider(Protocol):
    """One external search API (Serper, SerpApi, Tavily …). Raises SearchUnavailable-like errors."""

    name: str

    async def search(self, query: str, *, gl: str, hl: str, num: int = 10) -> list[SearchHit]: ...


class Searcher(Protocol):
    """Cache-first search over the configured providers (search_cache → primary → fallback).

    Records usage (cost 0 for cache hits), drops deny-listed URLs, and raises only when every
    provider failed."""

    async def search(
        self, query: str, *, market: str = "ES", area: str | None = None, fresh: bool = False
    ) -> list[SearchHit]: ...


@dataclass(frozen=True)
class Page:
    """A fetched page: main content (markdown, tables kept) or PDF text (spec 003 R4)."""

    url: str  # final URL
    title: str
    text: str
    content_type: str = "text/html"
    reader: str = "main_content"  # main_content | pdf | site:<id>
    fetched_at: datetime | None = None
    from_cache: bool = False
    html: str | None = None  # raw HTML for site readers only; never stored
    document_id: str | None = None
    snapshot_id: str | None = None  # spec 011: the stored raw page of the fetch that produced this page

    def as_doc(self) -> WebDoc:
        return WebDoc(url=self.url, title=self.title, text=self.text, snippet_only=False, snapshot_id=self.snapshot_id)


class PageStore(Protocol):
    """Cache-first fetch under the fetch policy (deny-list, robots incl. Crawl-delay, rate, size).

    Returns None when the page is refused, empty or failed; the reason is stored with the page."""

    async def get(self, url: str, *, area: str | None = None) -> Page | None: ...

    def last_reason(self, url: str) -> str | None: ...
