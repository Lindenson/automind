"""Fixture search provider implementing the application `Search` port.

Scenario layout: tests/fixtures/scenarios/<name>/search.json and docs/*.txt

search.json:
  {"queries": [{"match": ["prado", "150"], "results": [{"url": ..., "title": ..., "doc": "prado150_spec.txt",
                                                         "snippet_only": false}]}],
   "default": []}

A query matches an entry when all its `match` words occur in the lower-cased query. Failures can be
injected per URL (`fail_urls`) to check that one source failing never fails the turn (FR-023).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from automind.application.ports import WebDoc
from automind.application.usage import current_budget
from automind.domain.evidence import is_denied

SCENARIOS = Path(__file__).resolve().parents[1] / "fixtures" / "scenarios"


@dataclass
class FixtureSearch:
    scenario: str
    fail_urls: set[str] = field(default_factory=set)
    credits_per_search: float = 2.0
    queries: list[str] = field(default_factory=list)
    extracted: list[str] = field(default_factory=list)

    _calls: dict[int, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.dir = SCENARIOS / self.scenario
        self.spec: dict[str, Any] = json.loads((self.dir / "search.json").read_text(encoding="utf-8"))

    def _doc(self, r: dict[str, Any]) -> WebDoc:
        text = (self.dir / "docs" / r["doc"]).read_text(encoding="utf-8") if r.get("doc") else r.get("text", "")
        return WebDoc(
            url=r["url"], title=r.get("title", r["url"]), text=text, snippet_only=r.get("snippet_only", False)
        )

    def _charge(self) -> None:
        b = current_budget.get()
        if b is not None:
            b.before_search(self.credits_per_search)
            b.after_search(self.credits_per_search)

    async def search(self, query: str, max_results: int = 5) -> list[WebDoc]:
        self._charge()
        self.queries.append(query)
        q = query.lower()
        for n, entry in enumerate(self.spec.get("queries", [])):
            if all(w.lower() in q for w in entry["match"]):
                calls = self._calls.get(n, 0)
                self._calls[n] = calls + 1
                by_call = entry.get("results_by_call")
                rows = by_call[min(calls, len(by_call) - 1)] if by_call else entry["results"]
                break
        else:
            rows = self.spec.get("default", [])
        docs = [self._doc(r) for r in rows if not is_denied(r["url"])]
        return docs[:max_results]

    async def extract(self, url: str) -> WebDoc | None:
        self._charge()
        self.extracted.append(url)
        if url in self.fail_urls:
            raise ConnectionError(f"injected failure for {url}")
        for entry in self.spec.get("queries", []):
            rows = entry.get("results") or [r for call in entry.get("results_by_call", []) for r in call]
            for r in rows:
                if r["url"] == url:
                    return self._doc({**r, "snippet_only": False})
        return None

    async def fill_full_text(self, docs: list[WebDoc]) -> None:
        for d in docs:
            if d.snippet_only and d.url not in self.fail_urls:
                full = await self.extract(d.url)
                if full and len(full.text) > len(d.text):
                    d.text, d.snippet_only = full.text, False
