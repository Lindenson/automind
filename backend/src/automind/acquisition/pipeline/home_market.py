"""A car sold only outside Europe (chat 2026-11-06, Deepal S09 vs Li Auto L9): its home market, its local name, what
the roles are told about it and the searches on that market. Split from `plan.py`.

Identified on its home market (CaseCar.market "CN"), it was researched on European sites only: no spec, no
consumption, "energy cost cannot be computed". Its specs, consumption, tests and reliability are read where it is
sold too — in that market's language, on the registry's sources there and on English sites that cover its cars
(config/search.yaml `abroad.<market>.research`); prices never (spec 009 FR-009).
"""

from __future__ import annotations

from typing import Any

from automind.acquisition.pipeline.contracts import JobSpec
from automind.acquisition.pipeline.domain.variant import VariantFacts
from automind.acquisition.pipeline.scope import note_candidates
from automind.acquisition.ports import AcqPorts
from automind.shared.research_order import plan as research_plan
from automind.shared.research_order import search_plan
from automind.shared.vehicle import markets


def home_market(v: VariantFacts, job: JobSpec) -> str | None:
    """The market outside Europe the car is sold on (the case's, else the variant's), or None."""
    m = (job.market or v.market or "ES").upper()
    return None if markets.european(m) else m


def local_name(ports: AcqPorts, v: VariantFacts, market: str) -> str:
    """The model's name on its market ("深蓝S09", "理想L9"; config/aliases.yaml local_names), else make + model."""
    names = ports.ref.aliases.local_names
    return str((names.get(f"{v.make}|{v.model}") or {}).get(market) or f"{v.make} {v.model}")


def home_target(ports: AcqPorts, v: VariantFacts, market: str | None) -> str | None:
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


async def home_queries(ports: AcqPorts, v: VariantFacts, job: JobSpec) -> list[search_plan.PlannedQuery]:
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
    local_sites = await _local_sites(ports, job.area, market, int(cfg.get("sites", 3)), en_sites)
    if local_sites:
        group = tuple(local_sites)
        out.append(search_plan.PlannedQuery(_fill(str(cfg.get("site_template") or "{local} {sites}"), v, local, group),
                                            "REGISTRY", job.area, market, group))  # fmt: skip
    if english and en_sites:
        out.append(search_plan.PlannedQuery(_fill(f"{english} {{sites}}", v, local, en_sites), "REGISTRY", job.area,
                                            market, en_sites))  # fmt: skip
    return out


def home_pages(ports: AcqPorts, market: str | None) -> int:
    """Pages read from the home-market searches of one job (config `research.pages`)."""
    return int(_home_cfg(ports, market).get("pages", 4)) if market else 0


def _home_cfg(ports: AcqPorts, market: str) -> dict[str, Any]:
    abroad = (ports.ref.search or {}).get("abroad") or {}
    return dict((abroad.get(market) or {}).get("research") or {})


async def _local_sites(ports: AcqPorts, area: str, market: str, n: int, en_sites: tuple[str, ...]) -> list[str]:
    """Up to `n` of the registry's plain sources of the area on that market (terms allow them, not an English site);
    its candidates among them are remembered for the job. None without the registry or when it fails."""
    reg = ports.registry
    sources = []
    if n > 0 and reg is not None:
        try:
            sources = await reg.sources_for(area, [market], n + 8)
        except Exception:  # noqa: BLE001 - research works without the registry
            sources = []
    picked = [s for s in sources if not _excluded(ports, s.domain) and s.domain not in en_sites
              and search_plan.plain_site(s.domain)][:n]  # fmt: skip
    note_candidates([s.domain for s in picked if s.unverified])
    return [s.domain for s in picked]


def _fill(template: str, v: VariantFacts, local: str, sites: tuple[str, ...] = ()) -> str:
    text = template.format(make=v.make, model=v.model, local=local,
                           sites=" OR ".join(f"site:{s}" for s in sites))  # fmt: skip
    return " ".join(text.split())


def _excluded(ports: AcqPorts, domain: str) -> bool:
    terms = ((ports.ref.search or {}).get("abroad") or {}).get("terms_exclude") or []
    d = domain.lower().removeprefix("www.")
    return any(d == x or d.endswith("." + x) for x in terms)
