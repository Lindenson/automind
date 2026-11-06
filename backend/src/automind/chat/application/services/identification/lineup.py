"""Brand line-up lookup (spec 005 R2, FR-007, FR-008, FR-011): the models of a make on sale in Spain, with sources.

Cache-first (`brand_lineups`, refreshed after `intake.lineup_ttl_days`). On a miss the acquisition engine reads
one Spanish search plus the official site (≤ `lineup_max_pages` pages, robots respected, deny-list never read) with
the `lineup` web reader (`acquisition.api.lineup`), and code here keeps only what the documents support:
- a model must be written in the text of its document;
- a price must be written in its excerpt, and the excerpt in the document;
- at least one source must be the official site or a page that states a price (otherwise nothing is stored).

A car not on the Spanish line-up is looked up on another market (chat 2026-11-06: Deepal S09, Li Auto L9): Europe
("EU"), the make's home market ("CN"), anywhere ("ANY"), cached per market. Outside Europe no price is kept (spec 009
FR-009: prices from European markets only), so a source there must be the maker's site or one the registry survey
found open (config/search.yaml `abroad.<market>.trusted`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from automind.acquisition.api import LineupEntry
from automind.chat.application.ports import Ports
from automind.chat.domain.intake.intake import LineupModel, country_of_url, european
from automind.shared.evidence import evidence
from automind.shared.infrastructure import db


@dataclass
class Lineup:
    make: str
    models: list[LineupModel] = field(default_factory=list)
    sources: list[dict[str, Any]] = field(default_factory=list)
    fetched_at: datetime | None = None


_PTS = {"petrol", "diesel", "hybrid", "mhev", "phev", "bev", "lpg"}


def _limits(ports: Ports) -> dict[str, Any]:
    return dict(ports.ref.search["intake"])


def _price_in(excerpt: str, price: int) -> bool:
    digits = re.sub(r"\D", "", excerpt)
    return str(price) in digits


def validate(make: str, entries: list[LineupEntry], docs: dict[str, tuple[str, str]], official: str | None,
             market: str = "ES", trusted: tuple[str, ...] = ()) -> Lineup:  # fmt: skip
    """Keep the entries their documents support (pure apart from the evidence helpers). Outside Europe no price is
    kept, and a source must be the maker's site or a `trusted` one. Outside Spain the maker's own country site counts
    as official (deepal.pl), and a European page names its country by its domain (owner 2026-11-06: "found on the
    Polish market")."""
    priced_market = european(market)
    out: list[LineupModel] = []
    used: dict[str, dict[str, Any]] = {}
    seen: set[str] = set()
    for e in entries:
        doc = docs.get(e.source_url)
        name = e.model.strip()
        if doc is None or not name or name.lower() in seen:
            continue
        title, text = doc
        if name.lower() not in f"{title}\n{text}".lower():
            continue  # a model not written in its document is never kept
        price = e.price_from_eur if priced_market else None
        if price is not None and not (5000 <= price <= 500000 and _price_in(e.excerpt, price)
                                      and evidence.occurs(e.excerpt, text)):  # fmt: skip
            price = None
        seen.add(name.lower())
        pts = tuple(p for p in (x.lower() for x in e.powertrains) if p in _PTS)
        country = country_of_url(e.source_url) if market != "ES" and priced_market else None
        out.append(LineupModel(model=name, body=e.body.lower(), powertrains=pts, price_from_eur=price,
                               source_url=e.source_url, country=country))  # fmt: skip
        used[e.source_url] = {"url": e.source_url, "name": title or e.source_url, "priced": price is not None}
    dom = official.split("/")[0].removeprefix("www.") if official else None

    slug = "".join(ch for ch in make.lower() if ch.isalnum())

    def _official(u: str) -> bool:  # the host itself, never a substring (nicebyd.com is not byd.com)
        d = evidence.domain_of(u)
        if market != "ES" and slug and d.split(".", 1)[0].replace("-", "").startswith(slug):
            return True  # the maker's site of another country (deepal.pl, deepal-polska.pl)
        return bool(dom) and (d == dom or d.endswith("." + dom))

    def _trusted(u: str) -> bool:
        d = evidence.domain_of(u)
        return any(d == t or d.endswith("." + t) for t in trusted)

    ok = any(_official(u) or src["priced"] or (not priced_market and _trusted(u)) for u, src in used.items())
    if not ok:
        return Lineup(make=make)
    srcs = [{"url": s["url"], "name": s["name"], "type": "MANUFACTURER" if _official(s["url"]) else "PUBLICATION"}
            for s in used.values()]  # fmt: skip
    return Lineup(make=make, models=out, sources=srcs, fetched_at=datetime.now(UTC))


def _row_of(make: str, market: str = "ES") -> Any:
    return select(db.BrandLineup).where(db.BrandLineup.make == make, db.BrandLineup.market == market)


async def cached(make: str, ttl_days: int, market: str = "ES") -> Lineup | None:
    async with db.sessionmaker()() as s:
        row = (await s.execute(_row_of(make, market))).scalar_one_or_none()
    if row is None or row.fetched_at < datetime.now(UTC) - timedelta(days=ttl_days):
        return None
    models = [LineupModel(model=m["model"], body=m.get("body", ""), powertrains=tuple(m.get("powertrains") or ()),
                          price_from_eur=m.get("price_from_eur"), source_url=m.get("source_url"),
                          country=m.get("country")) for m in row.models]  # fmt: skip
    return Lineup(make=make, models=models, sources=list(row.sources), fetched_at=row.fetched_at)


async def store(lu: Lineup, market: str = "ES") -> None:
    models = [{"model": m.model, "body": m.body, "powertrains": list(m.powertrains),
               "price_from_eur": m.price_from_eur, "source_url": m.source_url, "country": m.country}
              for m in lu.models]  # fmt: skip
    async with db.sessionmaker()() as s:
        row = (await s.execute(_row_of(lu.make, market))).scalar_one_or_none()
        if row is None:
            row = db.BrandLineup(make=lu.make, market=market)
            s.add(row)
        row.models, row.sources, row.fetched_at = models, lu.sources, lu.fetched_at or datetime.now(UTC)
        await s.commit()


async def get_lineup(ports: Ports, make: str, market: str = "ES") -> Lineup | None:
    """The make's line-up in Spain, or on `market` for a car not sold in Spain (cache-first), or None when no source
    supports one."""
    lim = _limits(ports)
    if (hit := await cached(make, int(lim["lineup_ttl_days"]), market)) is not None:
        return hit
    reg = ports.ref.makes
    if reg is None:
        official = None
    elif market == "ES":
        official = reg.site(make)
    else:
        official = reg.site_on(make, market)
    if ports.acquisition is None:
        return None
    pages = int(lim["lineup_max_pages"])
    if market == "ES":
        read = await ports.acquisition.lineup(make, official=official, max_pages=pages)
    else:
        read = await ports.acquisition.lineup(make, official=official, max_pages=pages, market=market)
    if read is None:
        return None
    cfg = dict(((ports.ref.search or {}).get("abroad") or {}).get(market) or {})
    lu = validate(make, read.out.models, read.docs, official, market, tuple(str(t) for t in cfg.get("trusted") or ()))
    if not lu.models:
        return None
    await store(lu, market)
    return lu
