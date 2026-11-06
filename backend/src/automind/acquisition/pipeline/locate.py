"""S2 locate (spec 011 strangler, research R5): run the planned searches (cache-first), rank what they found
(favourites and the registry's order first, then authority and rank), skip what the registry blocks and what the job
already used, and hand the ranked URLs to the fetch stage. `pages_for` is one job's whole search: the planned
queries, the warranty page, the shorter retries, the registry's `site:` queries and the assistant's follow-up
queries. Moved from `application/research.py` with the bodies unchanged.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from automind.acquisition.pipeline import fetch
from automind.acquisition.pipeline.plan import (
    SITE_QUERY_PAGES,
    _ai_queries,
    current_plan,
    home_market,
    home_pages,
    home_queries,
    identity_of,
    market_names,
    queries_for,
    registry_queries,
)
from automind.acquisition.ports import AcqPorts
from automind.shared.contracts.web import Page
from automind.shared.evidence import evidence as ev
from automind.shared.infrastructure import db
from automind.shared.research_order import search_plan

if TYPE_CHECKING:
    from automind.acquisition.pipeline.job import JobSpec

VERSION = "locate@2"  # 2: the home-market searches (chat 2026-11-06)

Emit = Callable[[str, str], Awaitable[None]]


NO_FAVOURITE = 9


def favourite_priority(ports: AcqPorts, v: db.Variant | None, url: str) -> int | None:
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


def _skipped(url: str) -> bool:
    """Blocked in the registry (classifieds, terms forbid, robots): never read (spec 010 US7 hard limits)."""
    plan = current_plan.get()
    if plan is None or not plan.skip:
        return False
    d = ev.domain_of(url)
    return any(d == x or d.endswith("." + x) for x in plan.skip)


def terms_excluded(ports: AcqPorts, url: str) -> bool:
    """A site whose terms forbid commercial use (config/search.yaml `abroad.terms_exclude`: pcauto, autohome) is
    never read, whichever search found it (chat 2026-11-06: the Chinese queries find them first)."""
    terms = ((ports.ref.search or {}).get("abroad") or {}).get("terms_exclude") or []
    d = ev.domain_of(url)
    return any(d == x or d.endswith("." + x) for x in terms)


WARRANTY_PAGES = 3  # pages read for the brand's warranty terms in round 0 of the manufacturer area


def _rank_hits(
    ports: AcqPorts, v: db.Variant | None, planned: list[search_plan.PlannedQuery], results: list[Any], seen: set[str]
) -> tuple[dict[str, tuple[int, int, int]], dict[str, str], list[search_plan.PlannedQuery], int]:
    """Favourites first, then by authority and rank; also which market found a URL and which queries were empty."""
    from automind.shared.metering.usage import BudgetExceeded as _BE  # noqa: PLC0415

    ranked: dict[str, tuple[int, int, int]] = {}
    url_market: dict[str, str] = {}
    empty: list[search_plan.PlannedQuery] = []
    failures = 0
    for q, r in zip(planned, results, strict=True):
        if isinstance(r, _BE):
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
    v: db.Variant | None = None,
    *,
    fresh: bool = False,
) -> Located:
    """Search (cache-first) → rank favourites first (R2)."""
    results = await asyncio.gather(
        *(ports.search.search(q.text, market=q.market, area=area, fresh=fresh) for q in planned),
        return_exceptions=True,
    )
    return Located(*_rank_hits(ports, v, planned, results, seen))


async def _collect(
    ports: AcqPorts,
    planned: list[search_plan.PlannedQuery],
    seen: set[str],
    area: str,
    v: db.Variant | None = None,
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


async def pages_for(
    ports: AcqPorts, v: db.Variant, job: JobSpec, missing: list[str], seen: set[str], emit: Emit
) -> tuple[list[search_plan.PlannedQuery], list[Page], dict[str, Any]]:
    planned = queries_for(ports, v, job.area, job.round, missing, car_year=job.car_year)
    if job.fresh and job.round == 0:  # search again: favourites and the open web together, past the cache
        more = queries_for(ports, v, job.area, 1, missing, car_year=job.car_year)
        planned += [q for q in more if q.text not in {p.text for p in planned}]
    warranty = search_plan.warranty_query(planned, job.area, job.round, identity_of(v), ports.ref.favourite_queries)
    await emit(
        "searching", f"{job.area}: {len(planned) + len(warranty)} searches" + (" (follow-up)" if job.round else "")
    )
    pages, stats = await _collect(ports, planned, seen, job.area, v, fresh=job.fresh)
    if warranty:  # spec 008 FR-027: its own few pages, so blocked analyst sites ranked first cannot crowd it out
        more, more_stats = await _collect(ports, warranty, seen | {p.url for p in pages}, job.area, v,
                                          fresh=job.fresh, limit=WARRANTY_PAGES)  # fmt: skip
        pages += more
        planned += warranty
        stats = _merge_stats(stats, more_stats)
    retry_on = bool((ports.ref.search or {}).get("favourite_retry", True))
    retry = search_plan.retry_queries(stats["empty_queries"], identity_of(v), ports.ref.favourite_queries,
                                      market_names(ports, v))  # fmt: skip
    if retry_on and retry:  # a favourite query found nothing: once more, shorter (spec 007 FR-021)
        await emit("searching", f"{job.area}: {len(retry)} shorter searches")
        more, more_stats = await _collect(ports, retry, seen | {p.url for p in pages}, job.area, v)
        pages += more
        planned += retry
        stats = _merge_stats(stats, more_stats)
    home = [q for q in await home_queries(ports, v, job) if q.text not in {p.text for p in planned}]
    if home:  # a car sold only outside Europe: its own market's pages, in its language (chat 2026-11-06)
        await emit("searching", f"{job.area}: {len(home)} searches on the car's home market")
        more, more_stats = await _collect(ports, home, seen | {p.url for p in pages}, job.area, v, fresh=job.fresh,
                                          limit=home_pages(ports, home_market(v, job)))  # fmt: skip
        pages += more
        planned += home
        stats = _merge_stats(stats, more_stats)
    site = await registry_queries(ports, v, job, planned)
    if site:  # spec 010: the registry's sources, with their own few pages so the favourites cannot crowd them out
        await emit("searching", f"{job.area}: {len(site)} searches on registered sources")
        limit = int((ports.ref.registry or {}).get("site_query_pages_per_job", SITE_QUERY_PAGES))
        more, more_stats = await _collect(ports, site, seen | {p.url for p in pages}, job.area, v,
                                          fresh=job.fresh, limit=limit)  # fmt: skip
        pages += more
        planned += site
        stats = _merge_stats(stats, more_stats)
    if job.round > 0 and len(pages) < 2:  # open web found too little: bounded AI-proposed queries (FR-004)
        extra = await _ai_queries(ports, v, job.area, missing, [q.text for q in planned])
        if extra:
            await emit("searching", f"{job.area}: {len(extra)} more searches suggested by the assistant")
            more, more_stats = await _collect(ports, extra, seen | {p.url for p in pages}, job.area, v)
            pages += more
            planned += extra
            stats = _merge_stats(stats, more_stats)
    return planned, pages, stats


def _merge_stats(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    rej = dict(a["pages_rejected"])
    for k, n in b["pages_rejected"].items():
        rej[k] = rej.get(k, 0) + n
    return {
        "pages_found": a["pages_found"] + b["pages_found"],
        "pages_cached": a["pages_cached"] + b["pages_cached"],
        "pages_rejected": rej,
        "search_failures": a["search_failures"] + b["search_failures"],
        "url_market": {**b.get("url_market", {}), **a.get("url_market", {})},
        "empty_queries": [*a.get("empty_queries", []), *b.get("empty_queries", [])],
    }
