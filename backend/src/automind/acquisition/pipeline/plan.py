"""S1 plan (spec 011 strangler, research R5): what to search for one job — the area's markets and model names, the
favourite / open-web / registry `site:` queries, the registry's plan for the job and the assistant's follow-up
queries. The searches on a car's home market outside Europe are `home_market.py`.
"""

from __future__ import annotations

import dataclasses

from pydantic import BaseModel

from automind.acquisition.pipeline.contracts import JobSpec
from automind.acquisition.pipeline.domain.variant import CarVariant, VariantFacts
from automind.acquisition.pipeline.scope import note_candidates
from automind.acquisition.ports import AcqPorts
from automind.acquisition.registry.api import Plan
from automind.shared.metering.usage import BudgetExceeded
from automind.shared.research_order import plan as research_plan
from automind.shared.research_order import search_plan
from automind.shared.vehicle import specs

VERSION = "plan@2"  # 2: home-market research of a car sold only outside Europe (chat 2026-11-06)


def known_makes(ports: AcqPorts) -> list[str]:
    """Canonical makes (config/makes.yaml), so a brand page about another make is not taken for ours."""
    makes = getattr(ports.ref, "makes", None)
    return list(getattr(makes, "makes", None) or [])


async def variant(ports: AcqPorts, variant_id: str) -> CarVariant:
    """The job's variant. Raises ValueError for an unknown one (the job fails)."""
    v = await ports.stores.variants.load(variant_id)
    if v is None:
        raise ValueError(f"unknown variant {variant_id}")
    return v


def identity_of(v: VariantFacts) -> search_plan.Identity:
    years = f"{v.generation_years_from}-{v.generation_years_to or ''}" if v.generation_years_from else ""
    return search_plan.Identity(v.make, v.model, v.generation, v.variant_name, years)


def market_names(ports: AcqPorts, v: VariantFacts) -> dict[str, str]:
    """The model's name per market (spec 009 FR-021; config/aliases.yaml market_names)."""
    return search_plan.market_names_of(getattr(getattr(ports.ref, "aliases", None), "market_names", None), v.make,
                                       v.model, v.generation)  # fmt: skip


def area_markets(ports: AcqPorts, area: str) -> list[str]:
    cfg = ports.ref.search or {}
    return list((cfg.get("area_markets") or {}).get(area) or cfg.get("default_markets") or ["ES"])


def queries_for(
    ports: AcqPorts,
    v: VariantFacts,
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


async def registry_queries(ports: AcqPorts, v: VariantFacts, job: JobSpec,
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
    note_candidates([s.domain for s in sources if s.unverified])
    ident = identity_of(v)
    if job.area == "used_price" and job.car_year:
        ident = dataclasses.replace(ident, years=str(job.car_year))
    return search_plan.registry_queries(
        job.area, ident, [(s.site, s.market) for s in sources], ports.ref.favourite_queries, exclude=exclude,
        domains_per_query=per_query, max_queries=per_area, market_names=market_names(ports, v),
    )  # fmt: skip


PLAN_MARKETS = ["ES", "EN", "DE", "FR", "IT", "PT", "NL"]


async def registry_plan(ports: AcqPorts, job: JobSpec) -> Plan | None:
    """The registry's plan for the job (source order, the domains never to read, its candidates), for the job's
    make when the variant loads; None without the registry. A registry failure propagates (the job does not start)."""
    if ports.registry is None:
        return None
    try:
        v = await variant(ports, job.variant_id) if job.area not in research_plan.MARKET_AREAS else None
    except Exception:  # noqa: BLE001 - a plan without the make: the registry's order for every make
        v = None
    the_plan: Plan = await ports.registry.plan(job.area, PLAN_MARKETS, v.make if v is not None else None)
    return the_plan


class QueryProposals(BaseModel):
    """The query planner role's answer."""

    queries: list[str]


async def ai_queries(
    ports: AcqPorts, v: VariantFacts, area: str, missing: list[str], tried: list[str]
) -> list[search_plan.PlannedQuery]:
    """Up to `ai_followup.max_queries_per_area` queries the query planner role proposes for a follow-up round that
    found too few pages (FR-004), each new and plausible; none when the role fails. BudgetExceeded propagates."""
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
