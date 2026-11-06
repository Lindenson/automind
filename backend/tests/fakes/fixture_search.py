"""Fixture search implementing the application `Searcher` and `PageStore` ports (spec 003).

Scenario layout: tests/fixtures/scenarios/<name>/search.json and docs/*.txt

search.json:
  {"queries": [{"match": ["prado", "150"], "results": [{"url": ..., "title": ..., "doc": "prado150_spec.txt"}]}],
   "default": []}

A query matches an entry when all its `match` words occur in the lower-cased query. `search` returns
hits (no page text); `get(url)` returns the fixture document as a page. Failures can be injected per URL
(`fail_urls`): the page store then returns None, as the real one does, so one source failing never
fails the turn (FR-023).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from automind.shared.contracts.web import Page, SearchHit
from automind.shared.evidence import is_denied
from automind.shared.metering.usage import current_budget

SCENARIOS = Path(__file__).resolve().parents[1] / "fixtures" / "scenarios"


@dataclass
class FixtureSearch:
    scenario: str
    fail_urls: set[str] = field(default_factory=set)
    eur_per_search: float = 0.001
    queries: list[str] = field(default_factory=list)
    extracted: list[str] = field(default_factory=list)  # URLs read through the page store
    markets: list[str] = field(default_factory=list)

    _calls: dict[int, int] = field(default_factory=dict)
    _reasons: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.dir = SCENARIOS / self.scenario
        self.spec: dict[str, Any] = json.loads((self.dir / "search.json").read_text(encoding="utf-8"))

    def _text(self, r: dict[str, Any]) -> str:
        return (self.dir / "docs" / r["doc"]).read_text(encoding="utf-8") if r.get("doc") else r.get("text", "")

    def _charge(self) -> None:
        b = current_budget.get()
        if b is not None:
            b.before_search_eur(self.eur_per_search)
            b.after_search_eur(self.eur_per_search)

    def _rows(self, query: str) -> list[dict[str, Any]]:
        q = query.lower()
        for n, entry in enumerate(self.spec.get("queries", [])):
            if all(w.lower() in q for w in entry["match"]):
                calls = self._calls.get(n, 0)
                self._calls[n] = calls + 1
                by_call = entry.get("results_by_call")
                return list(by_call[min(calls, len(by_call) - 1)] if by_call else entry["results"])
        return list(self.spec.get("default", []))

    async def search(
        self, query: str, *, market: str = "ES", area: str | None = None, fresh: bool = False
    ) -> list[SearchHit]:
        self._charge()
        self.queries.append(query)
        self.markets.append(market)
        return [
            SearchHit(url=r["url"], title=r.get("title", r["url"]), snippet=self._text(r)[:200], rank=i + 1)
            for i, r in enumerate(self._rows(query))
            if not is_denied(r["url"])
        ]

    def _all_rows(self) -> list[dict[str, Any]]:
        out = []
        for entry in self.spec.get("queries", []):
            out += entry.get("results") or [r for call in entry.get("results_by_call", []) for r in call]
        return out + list(self.spec.get("default", []))

    async def get(self, url: str, *, area: str | None = None) -> Page | None:
        self.extracted.append(url)
        if url in self.fail_urls:
            self._reasons[url] = "ConnectionError"
            return None
        if is_denied(url):
            self._reasons[url] = "site is on the deny-list"
            return None
        for r in self._all_rows():
            if r["url"] == url:
                html = (self.dir / "docs" / r["html_doc"]).read_text(encoding="utf-8") if r.get("html_doc") else None
                return Page(url=url, title=r.get("title", url), text=self._text(r), reader="main_content", html=html)
        self._reasons[url] = "not in fixture"
        return None

    def last_reason(self, url: str) -> str | None:
        return self._reasons.get(url)
