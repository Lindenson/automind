"""Search plan (spec 003 FR-002, FR-003; research R2). Pure.

Round 0 queries the favourite sites of the area for each market, grouped into `site:a OR site:b`
queries in priority order (the official manufacturer site first when one is given). Later rounds use
the open-web templates. Deny-listed sites never appear. Queries are built by code, never by an AI.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from automind.domain.evidence import is_denied

Kind = Literal["FAVOURITE", "OPEN", "AI"]


@dataclass(frozen=True)
class Identity:
    make: str
    model: str
    generation: str | None
    variant: str
    years: str = ""


@dataclass(frozen=True)
class PlannedQuery:
    text: str
    kind: Kind
    area: str
    market: str
    sites: tuple[str, ...] = ()


def _render(template: str, car: Identity, sites: Sequence[str] = ()) -> str:
    text = template.format(
        make=car.make,
        model=car.model,
        generation=car.generation or "",
        variant=car.variant,
        years=car.years,
        sites=" OR ".join(f"site:{s}" for s in sites),
    )
    return " ".join(text.split())


def favourite_sites(area: str, market: str, favourites: Sequence[Mapping[str, Any]]) -> list[str]:
    """Favourite domains for an area and market (ANY matches every market), by priority then config order."""
    chosen = [
        (int(f.get("priority", 3)), i, str(f["domain"]))
        for i, f in enumerate(favourites)
        if area in f.get("areas", ()) and (market in f.get("markets", ()) or "ANY" in f.get("markets", ()))
    ]
    return [d for _, _, d in sorted(chosen) if not is_denied(f"https://{d}/")]


def queries(
    area: str,
    car: Identity,
    markets: Sequence[str],
    favourites: Sequence[Mapping[str, Any]],
    favourite_templates: Mapping[str, str],
    open_templates: Mapping[str, Sequence[str]],
    round_: int,
    *,
    manufacturer_site: str | None = None,
    sites_per_query: int = 4,
) -> list[PlannedQuery]:
    out: list[PlannedQuery] = []
    seen_text: set[str] = set()

    def add(q: PlannedQuery) -> None:
        if q.text and q.text not in seen_text:
            seen_text.add(q.text)
            out.append(q)

    if round_ == 0:
        template = favourite_templates.get(area)
        if not template:
            return out
        used: set[str] = set()
        for market in dict.fromkeys(markets):  # keep order, drop duplicates
            sites = favourite_sites(area, market, favourites)
            official = manufacturer_site and market == "ES" and area in ("price", "specs", "maintenance")
            if official and manufacturer_site and not is_denied(f"https://{manufacturer_site}/"):
                sites = [manufacturer_site, *sites]
            sites = [s for s in dict.fromkeys(sites) if s not in used]
            used.update(sites)
            for i in range(0, len(sites), max(1, sites_per_query)):
                group = tuple(sites[i : i + sites_per_query])
                add(PlannedQuery(_render(template, car, group), "FAVOURITE", area, market, group))
        return out
    first_market = markets[0] if markets else "ES"
    for t in open_templates.get(area, ()):
        add(PlannedQuery(_render(t, car), "OPEN", area, first_market))
    return out


def accept_ai_query(text: str, tried: Sequence[str], *, max_len: int = 200) -> bool:
    """Code check for an AI-proposed follow-up query (FR-004): length, no deny-listed site, not a repeat."""
    t = " ".join(text.split())
    if not t or len(t) > max_len:
        return False
    if t.lower() in {" ".join(x.split()).lower() for x in tried}:
        return False
    for token in t.replace("site:", " ").split():
        if "." in token and is_denied(f"https://{token.strip('()')}/"):
            return False
    return True
