"""Versions of a model generation sold in Spain, with sources: the input of the identification ladder
(domain/ladder.py, spec 008 US6).

Cache-first (the `versions` port: table `model_versions`, shared by every chat, refreshed after
`intake.versions_ttl_days`). On a miss: Spanish searches for the model and the year (or generation),
≤ `intake.versions_max_pages` pages through the page store (robots respected, deny-list never read), the `versions`
web reader extracts, and code keeps only what the documents support (FR-017): the power of each version is written
in its excerpt, the excerpt occurs in its document, and its years overlap the generation's. A new car whose first
searches find no list tries harder before the fallback (chat 5821ac77: an old catalog row won for a new Sorento):
the generation with the current year, the market's model name, and the registry's spec sources (`site:`).
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from automind.application.ports import Ports
from automind.application.usage import current_budget
from automind.domain import evidence, identity, search_plan
from automind.domain.ladder import Generation, Version, sold_in

_GEARBOX = Literal["manual", "automatic", "dct", "cvt", "e-cvt", "single"]


class _V(BaseModel):
    engine: str
    fuel: Literal["petrol", "diesel", "hybrid", "mhev", "phev", "bev", "lpg"] | None = None
    displacement_l: float | None = None
    power_cv: int | None = None
    power_kw: int | None = None
    gearboxes: list[_GEARBOX] = Field(default_factory=list)
    drives: list[Literal["FWD", "RWD", "AWD"]] = Field(default_factory=list)
    years_from: int | None = None
    years_to: int | None = None
    excerpt: str = ""
    source_url: str = ""


class VersionsOut(BaseModel):
    generation: str | None = None
    generation_years_from: int | None = None
    generation_years_to: int | None = None
    body_class: Literal["HATCHBACK", "SEDAN", "WAGON", "COUPE", "CONVERTIBLE", "SUV", "MPV", "PICKUP"] | None = None
    versions: list[_V] = Field(default_factory=list)


def _power_written(v: _V, text: str) -> bool:
    nums = {str(n) for n in (v.power_cv, v.power_kw) if n}
    return bool(nums & set(re.findall(r"\d{2,4}", text)))


def _overlaps(v: _V, lo: int | None, hi: int | None) -> bool:
    if lo is None or (v.years_from is None and v.years_to is None):
        return True
    a, b = v.years_from or v.years_to, v.years_to or v.years_from
    return (b or 0) >= lo - 1 and (hi is None or (a or 0) <= hi + 1)


def validate(out: VersionsOut, docs: dict[str, tuple[str, str]]) -> list[Version]:
    """The versions their documents support, one per engine and power, in the source's order (base first)."""
    kept: list[Version] = []
    seen: set[tuple[Any, ...]] = set()
    for v in out.versions:
        doc = docs.get(v.source_url)
        if doc is None or not v.engine.strip():
            continue
        if not _power_written(v, v.excerpt) or not evidence.occurs(v.excerpt, f"{doc[0]}\n{doc[1]}"):
            continue  # a power not written in its document is never kept
        if not _overlaps(v, out.generation_years_from, out.generation_years_to):
            continue  # a version of another generation
        kw = v.power_kw or (round(v.power_cv * 0.7355) if v.power_cv else None)
        cc = round(v.displacement_l * 1000) if v.displacement_l else None
        if cc is None and (e := identity.parse_engine(v.engine)) is not None and e.displacement_l:
            cc = round(e.displacement_l * 1000)
        ver = Version(engine=v.engine.strip()[:80], fuel=v.fuel, engine_cc=cc, power_kw=kw,
                      gearboxes=tuple(dict.fromkeys(v.gearboxes)), drives=tuple(dict.fromkeys(v.drives)),
                      years_from=v.years_from, years_to=v.years_to, source_url=v.source_url,
                      excerpt=v.excerpt[:240])  # fmt: skip
        if ver.engine_key in seen:
            continue
        seen.add(ver.engine_key)
        kept.append(ver)
    return kept


def _limits(ports: Ports) -> dict[str, Any]:
    return dict((ports.ref.search or {}).get("intake") or {})


# a page about one version (auto-data "...-150hp-12345", km77 ".../estandar/<version>/datos") lists one engine
_ONE_VERSION = re.compile(r"(-\d{2,4}(hp|cv|ps)-\d+|/estandar/[^/]+/datos|/ficha-tecnica/[^/]+-\d{2,4}-?cv)", re.I)
_RANGE = re.compile(r"(gama|precios|versiones|motores|range|configurador|/car-specs/|/vehicles/|/datos\b)", re.I)
_POWER = re.compile(r"\b(\d{2,3})\s?(?:CV|cv|hp|HP|PS|ps|CH)\b")


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


def _first_queries(when_query: str) -> list[str]:
    """Two searches: the range, the data sheet."""
    return [f"{when_query} gama motores versiones CV precios",
            f"{when_query} versiones motores potencia CV ficha técnica"]  # fmt: skip


HARDER_QUERIES = 3  # a new car without a list after the first searches: at most this many more
SPEC_SITES = 3  # registry spec sources in the `site:` query


async def _harder_queries(ports: Ports, make: str, model: str, generation: str | None, year: int) -> list[str]:
    """A new car: the range of the current year (with the generation code), under the model's Spanish market name,
    and on the registry's spec sources (spec 010; 009 FR-021)."""
    aliases = getattr(getattr(ports.ref, "aliases", None), "market_names", None)
    name = search_plan.market_names_of(aliases, make, model, generation).get("ES") or model
    out = [f"{make} {name} {generation or ''} {year} gama motores versiones CV".replace("  ", " ")]
    if name != model or generation:
        out.append(f"{make} {name} {year} precios versiones potencia CV")
    reg = getattr(ports, "registry", None)
    if reg is not None and hasattr(reg, "sources_for"):
        try:
            sites = [s.domain for s in await reg.sources_for("specs", ["ES", "ANY"], SPEC_SITES)]
        except Exception:  # noqa: BLE001 - the look-up works without the registry
            sites = []
        if sites:
            out.append(f"{make} {name} {year} " + " OR ".join(f"site:{d}" for d in sites[:SPEC_SITES]))
    return out[:HARDER_QUERIES]


async def _read(ports: Ports, make: str, queries: list[str], lim: dict[str, Any],
                done: set[str] | None = None) -> dict[str, tuple[str, str]]:  # fmt: skip
    """The searches, up to `versions_read_pages` pages read (range pages first; `done`: URLs read before, skipped
    and updated), the richest `versions_max_pages` kept. Identification, not research: counted apart."""
    budget = current_budget.get()
    before = budget.search_calls if budget is not None else 0
    done = done if done is not None else set()
    try:
        urls: list[str] = []
        for q in queries:
            for h in await ports.search.search(q, market="ES", area="specs"):
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


async def lookup(ports: Ports, make: str, model: str, *, generation: str | None, year: int | None,
                 new: bool, current_year: int | None = None) -> Generation | None:  # fmt: skip
    """The versions of this model in the generation asked (or the one built in `year`, or on sale now); None when
    there is no store or no document supports any version (the fallback identifies then, FR-020). A new car
    (`current_year` given) tries harder before giving up (the current year's range, the registry's spec sources)."""
    store = ports.versions
    if store is None or "versions" not in (ports.ref.prompts or {}):
        return None
    lim = _limits(ports)
    hit = await store.get(make, model, generation, year, new, int(lim.get("versions_ttl_days", 60)))
    if hit is not None and covers(hit, year):
        return hit  # type: ignore[no-any-return]
    when = " ".join(x for x in (generation, str(year) if year else None) if x) or "nuevo"
    read: set[str] = set()
    docs = await _read(ports, make, _first_queries(f"{make} {model} {when}"), lim, read)
    g = await _from_docs(ports, store, hit, make, model, generation, year, docs, lim) if docs else None
    if g is None and new and current_year:
        more = await _harder_queries(ports, make, model, generation, current_year)
        docs = await _read(ports, make, more, lim, read)
        g = await _from_docs(ports, store, hit, make, model, generation, year, docs, lim) if docs else None
    return g


async def _from_docs(ports: Ports, store: Any, hit: Generation | None, make: str, model: str,
                     generation: str | None, year: int | None, docs: dict[str, tuple[str, str]],
                     lim: dict[str, Any]) -> Generation | None:  # fmt: skip
    """The versions the documents list (the `versions` web reader, then code checks them); None when too few."""
    blob = "\n\n".join(f'<untrusted_document url="{u}">\n{t}\n{x[:7000]}\n</untrusted_document>'
                       for u, (t, x) in docs.items())  # fmt: skip
    ask = (f"Make: {make}\nModel: {model}\n" + (f"Generation: {generation}\n" if generation else "")
           + (f"Year built: {year}\n" if year else "Bought new now.\n") + f"\n{blob}")  # fmt: skip
    out = await ports.llm.structured("versions", VersionsOut, ports.ref.prompts["versions"], ask)
    kept = validate(out, docs)
    if hit is not None:  # the cached list did not cover the car's year: the versions found for it are added
        return await _merge(store, hit, kept, docs, year, int(lim.get("versions_min", 3)))
    gen = generation or out.generation
    # a list of one or two versions is a page about one version, not the range: it cannot say what does not
    # exist, so it is neither used nor kept (the fallback identifies, less certain)
    if len(kept) < int(lim.get("versions_min", 3)) or not gen:
        return None
    srcs = [{"url": u, "name": t or u} for u, (t, _) in docs.items() if any(v.source_url == u for v in kept)]
    g = Generation(make, model, gen, out.generation_years_from, out.generation_years_to, out.body_class, kept, srcs)
    await store.put(g)
    return g


def covers(g: Generation, year: int | None) -> bool:
    """Does the list say which versions were sold in `year`? (a version without years covers every year)"""
    if year is None:
        return True
    return any(sold_in(v, g.versions, year) for v in g.versions)


async def _merge(store: Any, g: Generation, kept: list[Version], docs: dict[str, tuple[str, str]], year: int | None,
                 minimum: int) -> Generation | None:  # fmt: skip
    """Versions of another part of the generation (a facelift) join the cached list; None when the year is still
    not covered by enough versions (the fallback identifies then)."""
    have = {(v.engine_key, v.years_from) for v in g.versions}
    add = [v for v in kept if (v.engine_key, v.years_from) not in have]
    if not add:
        return None
    srcs = [*g.sources, *({"url": u, "name": t or u} for u, (t, _) in docs.items()
                          if any(v.source_url == u for v in add))]  # fmt: skip
    merged = Generation(g.make, g.model, g.generation, g.years_from, g.years_to, g.body_class, [*g.versions, *add],
                        srcs)  # fmt: skip
    await store.put(merged)
    in_year = [v for v in merged.versions if year is None or sold_in(v, merged.versions, year)]
    return merged if len(in_year) >= minimum else None
