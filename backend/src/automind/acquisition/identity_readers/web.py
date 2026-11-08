"""The web identity readers (spec 011 strangler S8, research R5): the searches, pages and model roles that identify
a car — a make's line-up (`lineup` role), the versions of a model generation (`versions` role) and the search
results the resolver reads (`generation_hints`). Pages are read through the page store (robots respected, the
deny-list never read). The chat keeps its caches, the checks of what the readers return and its decisions.
Errors: the search, page store and model ports' errors pass through; the registry's sources are optional
(`market_sites` gives none when the registry fails).
"""

from __future__ import annotations

import re
from typing import Any

from automind.acquisition.api import LineupOut, LineupRead, VersionsOut, VersionsRead, WebHint
from automind.acquisition.identity_readers.searching import search_hits
from automind.acquisition.ports import AcqPorts
from automind.shared import evidence
from automind.shared.metering.usage import current_budget
from automind.shared.vehicle import markets

VERSION = "identity@1"


def abroad(ports: AcqPorts, market: str) -> dict[str, Any]:
    """config/search.yaml `abroad.<market>`: how a car not on the Spanish line-up is looked up there (a European
    country: Europe's entry, one market with no country preferred; another market without its own entry: ANY's)."""
    cfg = (ports.ref.search or {}).get("abroad") or {}
    fallback = markets.EUROPE if markets.european(market) else markets.ANYWHERE
    return dict(cfg.get(market) or cfg.get(fallback) or {})


async def market_sites(ports: AcqPorts, market: str, area: str = "specs") -> list[str]:
    """The registry's sources for `area` on a market (active, then surveyed candidates whose robots and terms allow
    them), without those whose terms forbid commercial use (search.yaml `abroad.terms_exclude`)."""
    cfg = abroad(ports, market)
    n = int(cfg.get("spec_sources") or 0)
    reg = ports.registry
    if n <= 0 or reg is None:
        return []
    exclude = [str(d) for d in ((ports.ref.search or {}).get("abroad") or {}).get("terms_exclude") or []]
    try:
        found = await reg.sources_for(area, [market], n + len(exclude))
    except Exception:  # noqa: BLE001 - the look-up works without the registry
        return []
    sites = [s.domain for s in found if not any(s.domain == d or s.domain.endswith("." + d) for d in exclude)]
    return sites[:n]


async def lineup(ports: AcqPorts, make: str, *, official: str | None, max_pages: int,
                 market: str = "ES") -> LineupRead | None:  # fmt: skip
    """One search on the market plus the official site, ≤ `max_pages` pages read through the page store (robots
    respected, deny-list never read), the `lineup` web reader extracts; None when no page could be read. Spain: a
    Spanish search; another market (a car not sold in Spain): that market's query and locale (search.yaml
    `abroad`)."""
    if market == "ES":
        hits = await search_hits(ports, f"{make} gama modelos precios España", market="ES", area="price")
    else:
        cfg = abroad(ports, market)
        query = str(cfg.get("lineup") or "{make} model lineup").format(make=make)
        hits = await search_hits(ports, query, market=str(cfg.get("search") or "ANY"), area="specs")
    urls = [f"https://www.{official}" if official else None] + [h.url for h in hits[:4]]
    docs: dict[str, tuple[str, str]] = {}
    for u in [x for x in urls if x and not evidence.is_denied(x)]:
        if len(docs) >= max_pages:
            break
        page = await ports.page_store.get(u, area="price" if market == "ES" else "specs")
        if page and page.text:
            docs[page.url] = (page.title or "", page.text[:12000])
    if not docs:
        return None
    blob = "\n\n".join(f'<untrusted_document url="{u}">\n{t}\n{x[:6000]}\n</untrusted_document>'
                       for u, (t, x) in docs.items())  # fmt: skip
    where = "" if market == "ES" else f"Market: {market} (the models sold there)\n"
    out = await ports.llm.structured("lineup", LineupOut, ports.ref.prompts["lineup"], f"Make: {make}\n{where}\n{blob}")
    return LineupRead(docs=docs, out=out)


# a page about one version (auto-data "...-150hp-12345", km77 ".../estandar/<version>/datos") lists one engine
_ONE_VERSION = re.compile(r"(-\d{2,4}(hp|cv|ps)-\d+|/estandar/[^/]+/datos|/ficha-tecnica/[^/]+-\d{2,4}-?cv)", re.I)

_RANGE = re.compile(r"(gama|precios|versiones|motores|range|configurador|/car-specs/|/vehicles/|/datos\b)", re.I)

_POWER = re.compile(r"\b(\d{2,3})\s?(?:CV|cv|hp|HP|PS|ps|CH)\b")


async def versions(
    ports: AcqPorts, make: str, model: str, generation: str | None, *, year: int | None, queries: list[str],
    limits: dict[str, Any], done: set[str] | None = None, market: str = "ES",
) -> VersionsRead | None:  # fmt: skip
    """The pages the searches find (range pages first, the richest kept) and what the `versions` web reader lists in
    them; None when no page could be read. `market`: the search locale (ES; another for a car not sold in Spain)."""
    docs = await _read(ports, make, queries, limits, done, market)
    if not docs:
        return None
    blob = "\n\n".join(f'<untrusted_document url="{u}">\n{t}\n{x[:7000]}\n</untrusted_document>'
                       for u, (t, x) in docs.items())  # fmt: skip
    ask = (f"Make: {make}\nModel: {model}\n" + (f"Generation: {generation}\n" if generation else "")
           + (f"Year built: {year}\n" if year else "Bought new now.\n") + f"\n{blob}")  # fmt: skip
    out = await ports.llm.structured("versions", VersionsOut, ports.ref.prompts["versions"], ask)
    return VersionsRead(docs=docs, out=out)


async def generation_hints(ports: AcqPorts, query: str, *, lineup_url: str | None = None, user_url: str | None = None,
                           prices: bool = False, market: str = "ES") -> list[WebHint]:  # fmt: skip
    """Search results for the resolver: generations and engines, and (new cars, `prices`) the Spanish price list of
    versions. The line-up page that lists the model and a page the user sent come first. A car not sold in Spain
    (`market`): that market's search and the registry's spec sources for it (search.yaml `abroad`)."""
    docs: list[WebHint] = []
    store = ports.page_store
    if lineup_url:
        page = await store.get(lineup_url, area="price")
        if page:
            docs.append(WebHint(url=page.url, title=page.title, text=page.text))
    if user_url:
        page = await store.get(user_url, area="specs")
        if page:
            docs.append(WebHint(url=page.url, title=page.title, text=page.text))
    hits = await search_hits(ports, f"{query} generation years engines specifications", market="EN", area="specs")
    if market != "ES":  # where the car is sold first: that market's search, then its registry spec sources
        cfg = abroad(ports, market)
        local = str(cfg.get("search") or "ANY")
        there = await search_hits(ports, str(cfg.get("hints") or "{query}").format(query=query), market=local,
                                          area="specs")  # fmt: skip
        sites = await market_sites(ports, market)
        on_sites = (await search_hits(ports, f"{query} " + " OR ".join(f"site:{d}" for d in sites), market=local,
                                              area="specs") if sites else [])  # fmt: skip
        merged = [*there[:3], *on_sites[:2], *hits]
        hits = [h for i, h in enumerate(merged) if all(h.url != x.url for x in merged[:i])]
    docs += [WebHint(url=h.url, title=h.title, text=h.snippet) for h in hits[: 5 if market == "ES" else 7]]
    # the snippets alone rarely give production years: read the top two pages too (cache-first)
    for h in hits[:2]:
        page = await store.get(h.url, area="specs")
        if page:
            docs.append(WebHint(url=page.url, title=page.title, text=page.text))
    if prices:  # versions and official prices, for the equal-level comparison (FR-029)
        found = await search_hits(ports, f"{query} precio versiones acabados España", market="ES", area="price")
        docs += [WebHint(url=h.url, title=h.title, text=h.snippet) for h in found[:3]]
    return docs


def _richest(read: dict[str, tuple[str, str]], n: int) -> dict[str, tuple[str, str]]:
    """The pages that list the most different powers (a range table, not an article about one version)."""

    def powers(text: str) -> int:
        return len(set(_POWER.findall(text[:7000])))

    ranked = sorted(read.items(), key=lambda kv: -powers(kv[1][1]))
    return {u: d for u, d in ranked[:n] if powers(d[1]) >= 2}


def _rank(url: str, make: str) -> int:
    """Pages that list the whole range first: the maker's own site, editorial range pages; one-version pages last
    (live check 2026-11-04: an A4 B9 "list" of one version from one km77 data page)."""
    score = 0
    if evidence.is_official(url) or make.lower().replace(" ", "") in url.lower().split("/")[2]:
        score += 3
    if "km77.com" in url:
        score += 2
    if _RANGE.search(url):
        score += 1
    if _ONE_VERSION.search(url):
        score -= 4
    return score


async def _read(ports: AcqPorts, make: str, queries: list[str], lim: dict[str, Any],
                done: set[str] | None = None, market: str = "ES") -> dict[str, tuple[str, str]]:  # fmt: skip
    """The searches, up to `versions_read_pages` pages read (range pages first; `done`: URLs read before, skipped
    and updated), the richest `versions_max_pages` kept. Identification, not research: counted apart."""
    budget = current_budget.get()
    before = budget.search_calls if budget is not None else 0
    done = done if done is not None else set()
    try:
        urls: list[str] = []
        for q in queries:
            for h in await search_hits(ports, q, market=market, area="specs"):
                if h.url not in urls and h.url not in done and not evidence.is_denied(h.url):
                    urls.append(h.url)
        urls.sort(key=lambda u: -_rank(u, make))  # stable: the search order within a rank
        read: dict[str, tuple[str, str]] = {}
        for url in urls[:12]:
            if len(read) >= int(lim.get("versions_read_pages", 6)):
                break
            done.add(url)
            page = await ports.page_store.get(url, area="specs")
            if page and page.text:
                read[page.url] = (page.title or "", page.text[:14000])
        docs = _richest(read, int(lim.get("versions_max_pages", 3)))
    finally:
        if budget is not None:  # identification, not research: counted apart (the turn's research needs consent)
            budget.identify_search_calls += budget.search_calls - before
    return docs
