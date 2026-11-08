"""S2 locate (spec 011 strangler, research R5): run the planned searches (cache-first), rank what they found
(favourites and the registry's order first, then authority and rank), skip what the registry blocks and what the job
already used, and hand the ranked URLs to the fetch stage (`collect`); one job's whole search is `searches.py`.
Moved from `application/research.py` with the bodies unchanged.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from automind.acquisition.pipeline import fetch
from automind.acquisition.pipeline.domain.variant import VariantFacts
from automind.acquisition.pipeline.scope import current_plan
from automind.acquisition.ports import AcqPorts
from automind.shared import evidence as ev
from automind.shared.contracts.web import Page
from automind.shared.metering.usage import BudgetExceeded
from automind.shared.research_order import search_plan

VERSION = "locate@2"  # 2: the home-market searches (chat 2026-11-06)

NO_FAVOURITE = 9


def favourite_priority(ports: AcqPorts, v: VariantFacts | None, url: str) -> int | None:
    """Priority of the favourite (or official manufacturer site) the URL belongs to, else None. With registry
    autonomy on, the registry's order replaces the configured favourites (spec 010 US6)."""
    dom = ev.domain_of(url)
    plan = current_plan.get()
    full = dom + "/" + url.split(dom, 1)[-1].lstrip("/") if dom in url else dom
    if v is not None and (m := ports.ref.manufacturer_sites.get(v.make)):
        host = m.split("/")[0].removeprefix("www.")
        if dom == host or dom.endswith("." + host):  # the host itself (never toyota.es.example.com)
            return 0
    if plan is not None and plan.autonomy:
        p = plan.priority_of(dom)
        return None if p is None else p + 1
    best = None
    for f in ports.ref.favourites:
        d = str(f["domain"])
        if dom == d or dom.endswith("." + d) or full.startswith(d):
            p = int(f.get("priority", 3))
            best = p if best is None else min(best, p)
    return best


def terms_excluded(ports: AcqPorts, url: str) -> bool:
    """A site whose terms forbid commercial use (config/search.yaml `abroad.terms_exclude`: pcauto, autohome) is
    never read, whichever search found it (chat 2026-11-06: the Chinese queries find them first)."""
    terms = ((ports.ref.search or {}).get("abroad") or {}).get("terms_exclude") or []
    d = ev.domain_of(url)
    return any(d == x or d.endswith("." + x) for x in terms)


@dataclass
class Located:
    """What the searches found: URL → rank key (favourite, authority, search rank), the market whose query found a
    URL first, the queries that found nothing and failed searches."""

    ranked: dict[str, tuple[int, int, int]]
    url_market: dict[str, str]
    empty: list[search_plan.PlannedQuery]
    failures: int

    @property
    def order(self) -> list[str]:
        return sorted(self.ranked, key=lambda u: self.ranked[u])


async def search(
    ports: AcqPorts,
    planned: list[search_plan.PlannedQuery],
    seen: set[str],
    area: str,
    v: VariantFacts | None = None,
    *,
    fresh: bool = False,
) -> Located:
    """Search (cache-first) → rank favourites first (R2)."""
    results = await asyncio.gather(
        *(ports.search.search(q.text, market=q.market, area=area, fresh=fresh) for q in planned),
        return_exceptions=True,
    )
    return Located(*_rank_hits(ports, v, planned, results, seen))


async def collect(
    ports: AcqPorts,
    planned: list[search_plan.PlannedQuery],
    seen: set[str],
    area: str,
    v: VariantFacts | None = None,
    *,
    fresh: bool = False,
    limit: int | None = None,
) -> tuple[list[Page], dict[str, Any]]:
    """Search (cache-first) → rank favourites first → fetch pages through the page store (R2–R4)."""
    found = await search(ports, planned, seen, area, v, fresh=fresh)
    limit = limit or int(ports.ref.search["limits"]["max_pages_per_job"])
    pages, rejected = await fetch.pages(ports.page_store, found.order, area, limit)
    stats = {
        "pages_found": len(found.ranked),
        "pages_cached": sum(1 for p in pages if p.from_cache),
        "pages_rejected": dict(rejected),
        "search_failures": found.failures,
        "url_market": found.url_market,
        "empty_queries": found.empty,
    }
    return pages, stats


def _skipped(url: str) -> bool:
    """Blocked in the registry (classifieds, terms forbid, robots): never read (spec 010 US7 hard limits)."""
    plan = current_plan.get()
    if plan is None or not plan.skip:
        return False
    d = ev.domain_of(url)
    return any(d == x or d.endswith("." + x) for x in plan.skip)


def _rank_hits(
    ports: AcqPorts, v: VariantFacts | None, planned: list[search_plan.PlannedQuery], results: list[Any], seen: set[str]
) -> tuple[dict[str, tuple[int, int, int]], dict[str, str], list[search_plan.PlannedQuery], int]:
    """Favourites first, then by authority and rank; also which market found a URL and which queries were empty."""
    ranked: dict[str, tuple[int, int, int]] = {}
    url_market: dict[str, str] = {}
    empty: list[search_plan.PlannedQuery] = []
    failures = 0
    for q, r in zip(planned, results, strict=True):
        if isinstance(r, BudgetExceeded):
            raise r
        if isinstance(r, BaseException):
            failures += 1
            continue
        if not r:
            empty.append(q)
        for h in r:
            url_market.setdefault(h.url, q.market)
            if h.url in seen or ev.is_denied(h.url) or _skipped(h.url) or terms_excluded(ports, h.url):
                continue
            fav = favourite_priority(ports, v, h.url)
            key = (NO_FAVOURITE if fav is None else fav, ev.AUTHORITY.index(ev.classify_source(h.url)), h.rank)
            ranked[h.url] = min(ranked.get(h.url, key), key)
    return ranked, url_market, empty, failures
