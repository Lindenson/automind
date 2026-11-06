"""S1 plan (spec 011 strangler, research R5): what to search for one job — the area's markets and model names, the
favourite / open-web / registry `site:` queries, the registry's plan for the job and the
assistant's follow-up queries. Moved from `application/research.py` with the bodies unchanged.
"""

from __future__ import annotations

import dataclasses
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from automind.acquisition.ports import AcqPorts
from automind.acquisition.registry.api import Plan
from automind.shared.infrastructure import db
from automind.shared.metering.usage import BudgetExceeded
from automind.shared.research_order import plan as research_plan
from automind.shared.research_order import search_plan
from automind.shared.vehicle import markets, specs

if TYPE_CHECKING:
    from automind.acquisition.pipeline.job import JobSpec

VERSION = "plan@2"  # 2: home-market research of a car sold only outside Europe (chat 2026-11-06)


def known_makes(ports: AcqPorts) -> list[str]:
    """Canonical makes (config/makes.yaml), so a brand page about another make is not taken for ours."""
    makes = getattr(ports.ref, "makes", None)
    return list(getattr(makes, "makes", None) or [])


def identity_of(v: db.Variant) -> search_plan.Identity:
    years = f"{v.generation_years_from}-{v.generation_years_to or ''}" if v.generation_years_from else ""
    return search_plan.Identity(v.make, v.model, v.generation, v.variant_name, years)


def market_names(ports: AcqPorts, v: db.Variant) -> dict[str, str]:
    """The model's name per market (spec 009 FR-021; config/aliases.yaml market_names)."""
    return search_plan.market_names_of(getattr(getattr(ports.ref, "aliases", None), "market_names", None), v.make,
                                       v.model, v.generation)  # fmt: skip


def area_markets(ports: AcqPorts, area: str) -> list[str]:
    cfg = ports.ref.search or {}
    return list((cfg.get("area_markets") or {}).get(area) or cfg.get("default_markets") or ["ES"])


def queries_for(
    ports: AcqPorts,
    v: db.Variant,
    area: str,
    round_: int,
    missing: list[str],
    car_year: int | None = None,
) -> list[search_plan.PlannedQuery]:
    """Favourites first (round 0), open web for later rounds or when an area has no favourites (R2)."""
    cfg = ports.ref.search or {}
    markets = area_markets(ports, area)
    names = market_names(ports, v)
    ident = identity_of(v)
    if area == "used_price" and car_year:  # spec 008 FR-023: the price of the car's model year, not the generation's
        ident = dataclasses.replace(ident, years=str(car_year))

    def plan(r: int) -> list[search_plan.PlannedQuery]:
        return search_plan.queries(
            area, ident, markets, ports.ref.favourites, ports.ref.favourite_queries,
            {area: ports.ref.queries.get(area, [])}, r,
            manufacturer_site=ports.ref.manufacturer_sites.get(v.make),
            sites_per_query=int(cfg.get("sites_per_query", 4)),
            market_names=names,
        )  # fmt: skip

    out = plan(round_) or (plan(1) if round_ == 0 else [])
    out += search_plan.ev_queries(out, ident, getattr(v, "powertrain", None), ports.ref.favourite_queries, names)
    if round_ > 0 and area in ("specs", "engineering") and missing:
        labels = ", ".join(specs.ATTRS[k].label for k in missing if k in specs.ATTRS)
        text = f"{v.make} {v.model} {v.generation or ''} {v.variant_name} {labels}"
        out.insert(0, search_plan.PlannedQuery(" ".join(text.split()), "OPEN", area, markets[0]))
    return out


SITE_QUERIES_PER_AREA = 4  # defaults; config/registry.yaml site_queries_per_area …
SITE_QUERY_DOMAINS = 3
SITE_QUERY_PAGES = 3


async def registry_queries(ports: AcqPorts, v: db.Variant, job: JobSpec,
                           planned: list[search_plan.PlannedQuery]) -> list[search_plan.PlannedQuery]:  # fmt: skip
    """`site:` queries to the registry's sources of the area (spec 010; 009 FR-009), whatever the autonomy flag:
    round 0 on the area's own markets, a follow-up round (an area below its minimum) on the other European markets
    and, except for prices, beyond. "Find it" (fresh) and the retry of an area an earlier run left short (escalate)
    try both at once. Sites already queried are skipped."""
    reg = getattr(ports, "registry", None)
    if reg is None or not hasattr(reg, "sources_for") or job.area in research_plan.MARKET_AREAS:
        return []
    cfg = ports.ref.registry or {}
    per_area = int(cfg.get("site_queries_per_area", SITE_QUERIES_PER_AREA))
    per_query = int(cfg.get("site_query_domains_per_query", SITE_QUERY_DOMAINS))
    own = area_markets(ports, job.area)
    markets = research_plan.registry_markets(job.area, own, job.round)
    if (job.fresh or job.escalate) and job.round == 0:
        markets += [m for m in research_plan.registry_markets(job.area, own, 1) if m not in markets]
    if not markets or per_area <= 0:
        return []
    exclude = [d for q in planned for d in q.sites]
    exclude += [str(f["domain"]) for f in ports.ref.favourites if job.area in f.get("areas", ())]
    if m := ports.ref.manufacturer_sites.get(v.make):
        exclude.append(m)
    try:
        sources = await reg.sources_for(job.area, markets, per_area * per_query + len(exclude))
    except Exception:  # noqa: BLE001 - research works without the registry
        return []
    candidates = current_candidates.get()
    if candidates is not None:
        candidates.update(s.domain for s in sources if s.unverified)
    ident = identity_of(v)
    if job.area == "used_price" and job.car_year:
        ident = dataclasses.replace(ident, years=str(job.car_year))
    return search_plan.registry_queries(
        job.area, ident, [(s.site, s.market) for s in sources], ports.ref.favourite_queries, exclude=exclude,
        domains_per_query=per_query, max_queries=per_area, market_names=market_names(ports, v),
    )  # fmt: skip


# --- a car sold only outside Europe (chat 2026-11-06, Deepal S09 vs Li Auto L9) ------------------------------------
# Identified on its home market (CaseCar.market "CN"), it was researched on European sites only: no spec, no
# consumption, "energy cost cannot be computed". Its specs, consumption, tests and reliability are read where it is
# sold too — in that market's language, on the registry's sources there and on English sites that cover its cars
# (config/search.yaml `abroad.<market>.research`); prices never (spec 009 FR-009).


def home_market(v: db.Variant, job: JobSpec) -> str | None:
    """The market outside Europe the car is sold on (the case's, else the variant's), or None."""
    m = (getattr(job, "market", None) or getattr(v, "market", None) or "ES").upper()
    return None if markets.european(m) else m


def _home_cfg(ports: AcqPorts, market: str) -> dict[str, Any]:
    abroad = (ports.ref.search or {}).get("abroad") or {}
    return dict((abroad.get(market) or {}).get("research") or {})


def local_name(ports: AcqPorts, v: db.Variant, market: str) -> str:
    """The model's name on its market ("深蓝S09", "理想L9"; config/aliases.yaml local_names), else make + model."""
    names = getattr(getattr(ports.ref, "aliases", None), "local_names", None) or {}
    return str((names.get(f"{v.make}|{v.model}") or {}).get(market) or f"{v.make} {v.model}")


def home_target(ports: AcqPorts, v: db.Variant, market: str | None) -> str | None:
    """What the extractor, the relevance role and the validator are told about a car sold only outside Europe: its
    market (its pages are the car's own sources, not "another market"), its local name, how those pages label the
    figures (config `research.target`)."""
    if market is None:
        return None
    cfg = _home_cfg(ports, market)
    local = local_name(ports, v, market)
    named = f", sold there as {local}" if local != f"{v.make} {v.model}" else ""
    where = str(cfg.get("name") or market)
    hint = str(cfg.get("target") or "").strip()
    return (f"market {market} ({where}; not sold in Europe{named}: pages of that market are about this car, never "
            f"'another market'){(' ' + hint) if hint else ''}")  # fmt: skip


def _fill(template: str, v: db.Variant, local: str, sites: tuple[str, ...] = ()) -> str:
    text = template.format(make=v.make, model=v.model, local=local,
                           sites=" OR ".join(f"site:{s}" for s in sites))  # fmt: skip
    return " ".join(text.split())


def _excluded(ports: AcqPorts, domain: str) -> bool:
    terms = ((ports.ref.search or {}).get("abroad") or {}).get("terms_exclude") or []
    d = domain.lower().removeprefix("www.")
    return any(d == x or d.endswith("." + x) for x in terms)


async def home_queries(ports: AcqPorts, v: db.Variant, job: JobSpec) -> list[search_plan.PlannedQuery]:
    """Searches on the car's home market for an area other than prices: the market-language queries with its local
    name, `site:` queries to the registry's sources of that market (robots and terms allow them; pcauto and autohome
    are excluded by their terms) and to English sites that cover that market's cars."""
    market = home_market(v, job)
    if market is None or job.area in research_plan.PRICE_AREAS or job.area in research_plan.MARKET_AREAS:
        return []
    cfg = _home_cfg(ports, market)
    templates = list((cfg.get("areas") or {}).get(job.area) or [])
    english = (cfg.get("english") or {}).get(job.area)
    if not templates and not english:
        return []
    local = local_name(ports, v, market)
    out = [search_plan.PlannedQuery(_fill(t, v, local), "OPEN", job.area, market) for t in templates]
    en_sites = tuple(str(d) for d in cfg.get("english_sites") or [] if not _excluded(ports, str(d)))
    n = int(cfg.get("sites", 3))
    reg = getattr(ports, "registry", None)
    sources = []
    if n > 0 and reg is not None and hasattr(reg, "sources_for"):
        try:
            sources = await reg.sources_for(job.area, [market], n + 8)
        except Exception:  # noqa: BLE001 - research works without the registry
            sources = []
    local_sites = [s for s in sources if not _excluded(ports, s.domain) and s.domain not in en_sites
                   and search_plan.plain_site(s.domain)][:n]  # fmt: skip
    candidates = current_candidates.get()
    if candidates is not None:
        candidates.update(s.domain for s in local_sites if s.unverified)
    if local_sites:
        group = tuple(s.domain for s in local_sites)
        out.append(search_plan.PlannedQuery(_fill(str(cfg.get("site_template") or "{local} {sites}"), v, local, group),
                                            "REGISTRY", job.area, market, group))  # fmt: skip
    if english and en_sites:
        out.append(search_plan.PlannedQuery(_fill(f"{english} {{sites}}", v, local, en_sites), "REGISTRY", job.area,
                                            market, en_sites))  # fmt: skip
    return out


def home_pages(ports: AcqPorts, market: str | None) -> int:
    """Pages read from the home-market searches of one job (config `research.pages`)."""
    return int(_home_cfg(ports, market).get("pages", 4)) if market else 0


PLAN_MARKETS = ["ES", "EN", "DE", "FR", "IT", "PT", "NL"]


async def _plan(ports: AcqPorts, job: JobSpec) -> Plan | None:
    if ports.registry is None:
        return None
    try:
        v = await _variant(job.variant_id) if job.area not in research_plan.MARKET_AREAS else None
    except Exception:  # noqa: BLE001
        v = None
    return await ports.registry.plan(job.area, PLAN_MARKETS, v.make if v is not None else None)


async def _variant(variant_id: str) -> db.Variant:
    async with db.sessionmaker()() as s:
        v = await s.get(db.Variant, variant_id)
    if v is None:
        raise ValueError(f"unknown variant {variant_id}")
    return v


class QueryProposals(BaseModel):
    queries: list[str]


async def _ai_queries(
    ports: AcqPorts, v: db.Variant, area: str, missing: list[str], tried: list[str]
) -> list[search_plan.PlannedQuery]:
    cfg = (ports.ref.search or {}).get("ai_followup") or {}
    limit = int(cfg.get("max_queries_per_area", 3))
    if limit <= 0 or "query_planner" not in ports.ref.prompts:
        return []
    ident = identity_of(v)
    user = (
        f"Vehicle: {ident.make} {ident.model} {ident.generation or ''} ({ident.years or 'years unknown'}), "
        f"{ident.variant}\nArea: {area}\nMissing: {', '.join(missing) or 'section minimum not met'}\n"
        "Tried:\n" + "\n".join(f"- {t}" for t in tried)
    )
    try:
        out = await ports.llm.structured("query_planner", QueryProposals, ports.ref.prompts["query_planner"], user)
    except BudgetExceeded:
        raise
    except Exception:  # noqa: BLE001 - no proposals is fine
        return []
    accepted: list[search_plan.PlannedQuery] = []
    for q in out.queries:
        if len(accepted) < limit and search_plan.accept_ai_query(q, [*tried, *(a.text for a in accepted)]):
            accepted.append(search_plan.PlannedQuery(" ".join(q.split()), "AI", area, "ES"))
    return accepted


# spec 010 US6-US8: the registry's plan for the running job (source order and the domains never to read)
current_plan: ContextVar[Plan | None] = ContextVar("current_plan", default=None)
# spec 011 FR-022 (010 T059): registry candidates the running job queried with `site:` (filled by registry_queries)
current_candidates: ContextVar[set[str] | None] = ContextVar("current_candidates", default=None)


def is_unverified(domain: str) -> bool:
    """A page of a registry candidate, from the job's plan or one of its `site:` queries: its values are labelled
    "unverified source" and its domain counts as half an independent source."""
    d = domain.lower().removeprefix("www.")
    plan = current_plan.get()
    if plan is not None and plan.unverified(d):
        return True
    return any(d == c or d.endswith("." + c) for c in current_candidates.get() or ())
