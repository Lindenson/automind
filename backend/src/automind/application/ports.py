"""Application ports: the interfaces the application layer depends on (constitution V, IX).

Infrastructure provides real implementations; tests provide fakes (tests/fakes). Application code
receives a `Ports` bundle instead of importing infrastructure, so graph workflows can run with a
scripted LLM and fixture search.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

from automind.domain.identity import Aliases

T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class Reference:
    """Static reference data from config/*.yaml, loaded by infrastructure and passed in."""

    aliases: Aliases
    generations: dict[str, list[tuple[str, int | None, int | None]]]
    questions: dict[str, str]
    prompts: dict[str, str]
    queries: dict[str, list[str]]
    criteria: Any = None  # domain.criteria.CriteriaModel (config/criteria.yaml)
    rates: dict[str, Any] | None = None  # config/rates.yaml (TCO)
    favourite_queries: dict[str, str] = field(default_factory=dict)  # area -> template with {sites}
    search: dict[str, Any] = field(default_factory=dict)  # config/search.yaml
    favourites: list[dict[str, Any]] = field(default_factory=list)  # config/sources.yaml favourites
    manufacturer_sites: dict[str, str] = field(default_factory=dict)  # make -> official ES site
    plausibility: dict[str, Any] = field(default_factory=dict)  # config/plausibility.yaml
    feasibility: dict[str, Any] = field(default_factory=dict)  # config/feasibility.yaml


@dataclass
class WebDoc:
    url: str
    title: str
    text: str
    snippet_only: bool


class LLM(Protocol):
    """Model access per role. Usage is charged to the current TurnBudget by the implementation."""

    async def structured(self, role: str, schema: type[T], system: str, user: str) -> T: ...

    async def text(self, role: str, system: str, user: str) -> str: ...

    def agent(self, role: str, tools: list[Any], system_prompt: str) -> Any:
        """A `create_agent`-compatible runnable for analyst roles (scoped MCP tools)."""
        ...


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

    def as_doc(self) -> WebDoc:
        return WebDoc(url=self.url, title=self.title, text=self.text, snippet_only=False)


class PageStore(Protocol):
    """Cache-first fetch under the fetch policy (deny-list, robots incl. Crawl-delay, rate, size).

    Returns None when the page is refused, empty or failed; the reason is stored with the page."""

    async def get(self, url: str, *, area: str | None = None) -> Page | None: ...

    def last_reason(self, url: str) -> str | None: ...


@dataclass(frozen=True)
class ReadingRow:
    attribute: str
    raw_value: str
    raw_unit: str | None
    excerpt: str  # the table row text, so the 002 excerpt validation still applies


@dataclass(frozen=True)
class SiteReading:
    reader: str
    rows: list[ReadingRow]
    ambiguous: bool = False


class SiteReaders(Protocol):
    """Deterministic table readers for favourite spec sites (spec 003 R6). None = layout not recognised."""

    def read(self, page: Page, target: dict[str, Any]) -> SiteReading | None: ...


class NoReaders:
    def read(self, page: Page, target: dict[str, Any]) -> SiteReading | None:
        return None


class CaseRepo(Protocol):
    async def latest(self, chat_id: str) -> tuple[int, dict[str, Any] | None, str | None]: ...

    async def save_version(self, chat_id: str, data: dict[str, Any], changed_by: str, change_log: list[str]) -> int: ...


class TurnRepo(Protocol):
    async def start(self, chat_id: str, user_message_id: str | None, case_version: int) -> Any: ...

    async def update(self, turn_id: str, **values: Any) -> None: ...

    async def get(self, turn_id: str) -> Any | None: ...

    async def active(self, chat_id: str) -> Any | None: ...

    async def last_report_fingerprint(self, chat_id: str) -> str | None: ...

    async def running(self) -> list[Any]: ...


class EventBus(Protocol):
    async def publish(self, chat_id: str, turn_id: str | None, type_: str, payload: dict[str, Any]) -> int: ...


class CatalogRepo(Protocol):
    async def find(self, make: str, model: str, generation: str | None, year: int | None) -> list[Any]: ...


class EvidenceRepo(Protocol):
    async def selected_values(self, variant_id: str) -> dict[str, Any]: ...


class JobRepo(Protocol):
    async def create(self, chat_id: str, turn_id: str, variant_id: str, area: str, round_: int) -> Any: ...

    async def mark(self, job_id: str, status: str, **values: Any) -> None: ...

    async def for_turn(self, turn_id: str) -> list[Any]: ...

    async def get(self, job_id: str) -> Any | None: ...

    async def skip_open(self, turn_id: str, reason: str = "cancelled") -> int: ...


class MessageRepo(Protocol):
    async def history(self, chat_id: str) -> list[Any]: ...


class Estimator(Protocol):
    """Research cost estimate (FR-041): jobs are (variant_id, area)."""

    async def estimate(self, jobs: list[tuple[str, str]], rounds: int) -> float: ...


class Clock(Protocol):
    def now(self) -> datetime: ...


Emit = Callable[[str, dict[str, Any]], Awaitable[None]]
"""Progress/event callback: (type, payload)."""


@dataclass
class Ports:
    llm: LLM
    search: Searcher
    cases: CaseRepo
    turns: TurnRepo
    events: EventBus
    jobs: JobRepo
    clock: Clock
    ref: Reference
    messages: MessageRepo
    estimator: Estimator
    pages: PageStore | None = None  # None → `search` also implements PageStore (test fakes)
    readers: SiteReaders = field(default_factory=NoReaders)
    feasibility: Any = None  # application.feasibility.FeasibilityStore (spec 003 US3)

    @property
    def page_store(self) -> PageStore:
        return self.pages if self.pages is not None else self.search  # type: ignore[return-value]
