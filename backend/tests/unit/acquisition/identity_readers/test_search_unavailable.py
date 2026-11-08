"""Identification without a search provider (2026-11-08 pre-prod: Serper "Not enough credits" failed the whole turn):
the line-up reads the maker's own site, the resolver's hints come from the pages it was given."""

from dataclasses import dataclass, field
from typing import Any

from automind.acquisition.api import LineupOut, WebHint
from automind.acquisition.identity_readers import web as readers
from automind.shared.contracts.web import SearchUnavailable


@dataclass
class _Page:
    url: str
    title: str = "Gama Kia"
    text: str = "Kia Sportage, Kia Niro, Kia EV6: precios y versiones"


@dataclass
class _NoSearch:
    asked: list[str] = field(default_factory=list)

    async def search(self, query: str, *, market: str = "ES", area: str | None = None, fresh: bool = False) -> Any:
        self.asked.append(query)
        raise SearchUnavailable("serper: HTTP 400")

    async def get(self, url: str, *, area: str | None = None) -> _Page:
        return _Page(url)


class _LLM:
    async def structured(self, role: str, schema: type, system: str, user: str) -> LineupOut:
        return LineupOut()


@dataclass
class _Ref:
    prompts: dict[str, str] = field(default_factory=lambda: {"lineup": "list the models"})
    search: dict[str, Any] = field(default_factory=dict)


@dataclass
class _Ports:
    search: _NoSearch = field(default_factory=_NoSearch)
    ref: _Ref = field(default_factory=_Ref)
    llm: _LLM = field(default_factory=_LLM)
    registry: object = None

    @property
    def page_store(self) -> _NoSearch:
        return self.search


async def test_lineup_reads_the_official_site_when_search_is_down() -> None:
    ports = _Ports()
    read = await readers.lineup(ports, "Kia", official="kia.com/es", max_pages=3)  # type: ignore[arg-type]
    assert ports.search.asked  # it tried
    assert read is not None and list(read.docs) == ["https://www.kia.com/es"]


async def test_hints_come_from_the_given_pages_when_search_is_down() -> None:
    hints = await readers.generation_hints(_Ports(), "Kia Sportage", user_url="https://example.es/sportage")  # type: ignore[arg-type]
    assert [h.url for h in hints] == ["https://example.es/sportage"] and isinstance(hints[0], WebHint)
