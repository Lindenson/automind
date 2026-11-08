"""S2 one job's whole search (spec 011 R5): the planned queries (favourites first, the open web too when the user
asked to search again), the brand's warranty page, the shorter retries of empty favourite queries, the car's home
market, the registry's `site:` queries and, in a follow-up round with too few pages, the assistant's queries — each
group with its own page limit so the earlier ones cannot crowd it out. Split from `locate.py`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from automind.acquisition.pipeline.domain.variant import VariantFacts
from automind.acquisition.pipeline.locate import collect
from automind.acquisition.pipeline.plan import (
    SITE_QUERY_PAGES,
    _ai_queries,
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
from automind.shared.research_order import search_plan

if TYPE_CHECKING:
    from automind.acquisition.pipeline.job import JobSpec

Emit = Callable[[str, str], Awaitable[None]]

WARRANTY_PAGES = 3  # pages read for the brand's warranty terms in round 0 of the manufacturer area


async def pages_for(
    ports: AcqPorts, v: VariantFacts, job: JobSpec, missing: list[str], seen: set[str], emit: Emit
) -> tuple[list[search_plan.PlannedQuery], list[Page], dict[str, Any]]:
    planned = queries_for(ports, v, job.area, job.round, missing, car_year=job.car_year)
    if job.fresh and job.round == 0:  # search again: favourites and the open web together, past the cache
        wider = queries_for(ports, v, job.area, 1, missing, car_year=job.car_year)
        planned += [q for q in wider if q.text not in {p.text for p in planned}]
    warranty = search_plan.warranty_query(planned, job.area, job.round, identity_of(v), ports.ref.favourite_queries)
    await emit(
        "searching", f"{job.area}: {len(planned) + len(warranty)} searches" + (" (follow-up)" if job.round else "")
    )
    pages, stats = await collect(ports, planned, seen, job.area, v, fresh=job.fresh)
    if warranty:  # spec 008 FR-027: its own few pages, so blocked analyst sites ranked first cannot crowd it out
        more, more_stats = await collect(ports, warranty, seen | {p.url for p in pages}, job.area, v,
                                          fresh=job.fresh, limit=WARRANTY_PAGES)  # fmt: skip
        pages += more
        planned += warranty
        stats = _merge_stats(stats, more_stats)
    retry_on = bool((ports.ref.search or {}).get("favourite_retry", True))
    retry = search_plan.retry_queries(stats["empty_queries"], identity_of(v), ports.ref.favourite_queries,
                                      market_names(ports, v))  # fmt: skip
    if retry_on and retry:  # a favourite query found nothing: once more, shorter (spec 007 FR-021)
        await emit("searching", f"{job.area}: {len(retry)} shorter searches")
        more, more_stats = await collect(ports, retry, seen | {p.url for p in pages}, job.area, v)
        pages += more
        planned += retry
        stats = _merge_stats(stats, more_stats)
    home = [q for q in await home_queries(ports, v, job) if q.text not in {p.text for p in planned}]
    if home:  # a car sold only outside Europe: its own market's pages, in its language (chat 2026-11-06)
        await emit("searching", f"{job.area}: {len(home)} searches on the car's home market")
        more, more_stats = await collect(ports, home, seen | {p.url for p in pages}, job.area, v, fresh=job.fresh,
                                          limit=home_pages(ports, home_market(v, job)))  # fmt: skip
        pages += more
        planned += home
        stats = _merge_stats(stats, more_stats)
    site = await registry_queries(ports, v, job, planned)
    if site:  # spec 010: the registry's sources, with their own few pages so the favourites cannot crowd them out
        await emit("searching", f"{job.area}: {len(site)} searches on registered sources")
        limit = int((ports.ref.registry or {}).get("site_query_pages_per_job", SITE_QUERY_PAGES))
        more, more_stats = await collect(ports, site, seen | {p.url for p in pages}, job.area, v,
                                          fresh=job.fresh, limit=limit)  # fmt: skip
        pages += more
        planned += site
        stats = _merge_stats(stats, more_stats)
    if job.round > 0 and len(pages) < 2:  # open web found too little: bounded AI-proposed queries (FR-004)
        extra = await _ai_queries(ports, v, job.area, missing, [q.text for q in planned])
        if extra:
            await emit("searching", f"{job.area}: {len(extra)} more searches suggested by the assistant")
            more, more_stats = await collect(ports, extra, seen | {p.url for p in pages}, job.area, v)
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
