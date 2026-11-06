"""Versions of a model generation sold in Spain, with sources: the input of the identification ladder
(domain/ladder.py, spec 008 US6).

Cache-first (the `versions` port: table `model_versions`, shared by every chat, refreshed after
`intake.versions_ttl_days`). On a miss the acquisition engine runs Spanish searches for the model and the year
(or generation), reads ≤ `intake.versions_max_pages` pages (robots respected, deny-list never read) with the
`versions` web reader (`acquisition.api.versions`), and code here keeps only what the documents support (FR-017):
the power of each version is written in its excerpt, the excerpt occurs in its document, and its years overlap the
generation's. A new car whose first
searches find no list tries harder before the fallback (chat 5821ac77: an old catalog row won for a new Sorento):
the generation with the current year, the market's model name, and the registry's spec sources (`site:`).

Before any search, a new car's registered versions are read from the open datasets (`acquisition.api.
dataset_versions`: stored gold, cached rows, else one bounded dataset query): an engine first registered after the
others (a facelift, the Sorento PHEV's 118 kW engine of 2024) names the year the searches ask for, and the same
versions are the options of the "which version?" question when no list is found (chat 6e001ee0).
"""

from __future__ import annotations

import re
from typing import Any

from automind.acquisition.api import DatasetVersion, VersionEntry, VersionsOut, VersionsRead
from automind.application.ports import Ports
from automind.domain import evidence, identity, intake, search_plan
from automind.domain.ladder import Generation, Version, sold_in


def _power_written(v: VersionEntry, text: str) -> bool:
    nums = {str(n) for n in (v.power_cv, v.power_kw) if n}
    return bool(nums & set(re.findall(r"\d{2,4}", text)))


def _overlaps(v: VersionEntry, lo: int | None, hi: int | None) -> bool:
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


def abroad_queries(ports: Ports, market: str, make: str, model: str, when: str) -> tuple[list[str], str]:
    """The versions searches for a car not sold in Spain, and their locale (config/search.yaml `abroad`)."""
    every = (ports.ref.search or {}).get("abroad") or {}
    cfg = dict(every.get(market) or every.get(intake.EUROPE if intake.european(market) else intake.ANYWHERE) or {})
    tpl = [str(q) for q in cfg.get("versions") or ["{make} {model} {when} versions specifications power kW"]]
    return [" ".join(q.format(make=make, model=model, when=when).split()) for q in tpl], str(cfg.get("search") or "ANY")


async def lookup(ports: Ports, make: str, model: str, *, generation: str | None, year: int | None,
                 new: bool, current_year: int | None = None,
                 fuel: str | None = None, market: str | None = None) -> Generation | None:  # fmt: skip
    """The versions of this model in the generation asked (or the one built in `year`, or on sale now); None when
    there is no store or no document supports any version (the fallback identifies then, FR-020). A new car
    (`current_year` given) tries harder before giving up (the current year's range, the registry's spec sources).
    `market`: a car not sold in Spain (chat 2026-11-06) is searched on the market where it is sold."""
    store = ports.versions
    if store is None or "versions" not in (ports.ref.prompts or {}):
        return None
    lim = _limits(ports)
    hit = await store.get(make, model, generation, year, new, int(lim.get("versions_ttl_days", 60)))
    if hit is not None and covers(hit, year):
        return hit  # type: ignore[no-any-return]
    if ports.acquisition is None:
        return None
    if market is not None:
        when = " ".join(x for x in (generation, str(year or "") or None) if x)
        queries, locale = abroad_queries(ports, market, make, model, when)
        got = await ports.acquisition.versions(make, model, generation, year=year, queries=queries, limits=lim,
                                               done=set(), market=locale)  # fmt: skip
        return await _from_docs(store, hit, make, model, generation, year, got, lim) if got else None
    since = None
    if new and current_year and year is None:  # the datasets first: cheap, and they know a facelift's year
        since = newer_engine_year(await dataset_versions(ports, make, model, generation, None,
                                                         current_year - DATASET_YEARS))  # fmt: skip
    when = " ".join(x for x in (generation, str(year or since or "") or None) if x) or "nuevo"
    read: set[str] = set()
    first = _first_queries(f"{make} {model} {when}")
    got = await ports.acquisition.versions(make, model, generation, year=year, queries=first, limits=lim, done=read)
    g = await _from_docs(store, hit, make, model, generation, year, got, lim) if got else None
    if g is None and new and current_year:
        more = await _harder_queries(ports, make, model, generation, current_year)
        got = await ports.acquisition.versions(make, model, generation, year=year, queries=more, limits=lim, done=read)
        g = await _from_docs(store, hit, make, model, generation, year, got, lim) if got else None
    if g is None and hit is None:  # no sourced list: a combustion car's registered versions build it (2026-11-05)
        min_regs = int(lim.get("dataset_versions_min_registrations", 10))
        found = await dataset_versions(ports, make, model, generation, fuel, None)
        g = registered_generation(found, make, model, generation, year, fuel, min_regs)
    return g


async def _from_docs(store: Any, hit: Generation | None, make: str, model: str, generation: str | None,
                     year: int | None, got: VersionsRead, lim: dict[str, Any]) -> Generation | None:  # fmt: skip
    """The versions the documents list (the engine's `versions` web reader, then code checks them); None when too
    few."""
    out, docs = got.out, got.docs
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


DATASET_YEARS = 6  # a new car: the registered versions of the last years


async def dataset_versions(ports: Ports, make: str, model: str, generation: str | None, fuel: str | None,
                           year_from: int | None) -> list[DatasetVersion]:  # fmt: skip
    """The model's versions registered in the EU (the engine's `dataset_versions`); [] without the engine."""
    get = getattr(getattr(ports, "acquisition", None), "dataset_versions", None)
    if get is None:
        return []
    try:
        return list(await get(make, model, generation, fuel, year_from))
    except Exception:  # noqa: BLE001 - the datasets only add options and a search year
        return []


DATASET_SOURCE = "EU registrations (EEA CO2 / RDW)"
ICE_FUELS = frozenset({"petrol", "diesel", "lpg", "cng"})
CV_PER_KW = 1.35962


def _span(xs: list[Any]) -> tuple[int | None, int | None]:
    lo = min((x.years_from for x in xs if x.years_from), default=None)
    hi = None if any(x.years_to is None for x in xs) else (max(x.years_to or 0 for x in xs) or None)
    return lo, hi


def registered_generation(found: list[DatasetVersion], make: str, model: str, generation: str | None,
                          year: int | None, fuel: str | None, min_regs: int) -> Generation | None:  # fmt: skip
    """The versions list of a petrol, diesel, LPG or CNG car built from its EU registrations (owner, 2026-11-05):
    a combustion engine's registered kW is the car's power. One version per (fuel, engine size, kW) with its years;
    the power in kW (the CV computed from it), gearbox and drive unknown (never invented). None for a hybrid,
    plug-in or electric car (its registered kW is not the system power), an unknown fuel with non-combustion rows,
    or when nothing is left after the registrations floor and the year (a used car: versions registered that year).
    Not kept in the versions cache: a web list found later wins."""
    if fuel is not None and fuel not in ICE_FUELS:
        return None
    rows = [x for x in found if fuel is None or x.fuel == fuel]
    if not rows or any(x.fuel not in ICE_FUELS or not x.power_is_max for x in rows):
        return None
    merged: dict[tuple[str, int | None, int], list[DatasetVersion]] = {}
    for x in rows:
        if x.engine_kw:
            merged.setdefault((x.fuel, x.displacement_cc, x.engine_kw), []).append(x)
    out: list[Version] = []
    for (f, cc, kw), xs in merged.items():
        regs = sum(x.registrations for x in xs)
        if regs and regs < min_regs:  # 0: a stored group key, its count not known
            continue
        lo, hi = _span(xs)
        if year is not None and lo is not None and not (lo <= year and (hi is None or year <= hi)):
            continue
        cv = round(kw * CV_PER_KW)
        size = f"{cc / 1000:.1f} " if cc else ""
        excerpt = (f"{DATASET_SOURCE}: {f}, {cc or '?'} cm3, {kw} kW registered (CV {cv} computed from the "
                   f"registered kW), {lo or ''}–{hi or ''}, {regs or '?'} registrations")  # fmt: skip
        url = next((x.source_url for x in xs if x.source_url), "")
        out.append(Version(engine=f"{size}{f} {kw} kW ({cv} CV)", fuel=f, engine_cc=cc, power_kw=kw,
                           years_from=lo, years_to=hi, source_url=url, excerpt=excerpt[:240]))  # fmt: skip
    if not out:
        return None
    out.sort(key=lambda v: (v.engine_cc or 0, v.power_kw or 0))  # the base version first
    lo, hi = _span(out)
    gen = generation or (f"{lo}–{hi or ''}" if lo else "")
    url = next((v.source_url for v in out if v.source_url), "")
    return Generation(make, model, gen, lo, hi, None, out, [{"url": url, "name": DATASET_SOURCE, "dataset": True}])


def newer_engine_year(found: list[DatasetVersion]) -> int | None:
    """The first year of the newest engine registered after the model's first ones (a facelift); None if all came
    together."""
    years = sorted({v.years_from for v in found if v.years_from})
    return years[-1] if len(years) > 1 else None


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
