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
from dataclasses import dataclass
from datetime import UTC, datetime

from automind.acquisition import api as acquisition
from automind.acquisition.api import LineupEntry, StoredLineup
from automind.chat.application.ports import Ports
from automind.chat.application.services.identification.contracts import Lineup
from automind.chat.domain.intake import LineupModel
from automind.shared import evidence
from automind.shared.vehicle.markets import country_of_url, european

POWERTRAINS = frozenset({"petrol", "diesel", "hybrid", "mhev", "phev", "bev", "lpg"})  # kept from a line-up entry
PRICE_RANGE = (5000, 500000)  # a "from" price outside it is a misread, never kept
_NOT_DIGIT = re.compile(r"\D")


@dataclass(frozen=True)
class _Origin:
    """Which source of a line-up counts as the maker's or as trusted, for a make on a market."""

    make: str
    market: str
    official: str | None  # the maker's site on the market ("byd.com/es")
    trusted: tuple[str, ...]  # other domains a line-up outside Europe may come from

    def official_page(self, url: str) -> bool:
        """The maker's own site — the host itself, never a substring (nicebyd.com is not byd.com); outside Spain also
        the maker's site of another country (deepal.pl, deepal-polska.pl)."""
        d = evidence.domain_of(url)
        slug = "".join(ch for ch in self.make.lower() if ch.isalnum())
        if self.market != "ES" and slug and d.split(".", 1)[0].replace("-", "").startswith(slug):
            return True
        if not self.official:
            return False
        dom = self.official.split("/")[0].removeprefix("www.")
        return bool(dom) and (d == dom or d.endswith("." + dom))

    def trusted_page(self, url: str) -> bool:
        d = evidence.domain_of(url)
        return any(d == t or d.endswith("." + t) for t in self.trusted)


def validate(make: str, entries: list[LineupEntry], docs: dict[str, tuple[str, str]], official: str | None,
             market: str = "ES", trusted: tuple[str, ...] = ()) -> Lineup:  # fmt: skip
    """Keep the entries their documents support (pure apart from the evidence helpers): a model written in its
    document, a price written in its excerpt. Outside Europe no price is kept, and a source must be the maker's site
    or a `trusted` one; with no source that is official, priced or trusted nothing is kept (an empty line-up).
    Outside Spain the maker's own country site counts as official (deepal.pl), and a European page names its country
    by its domain (owner 2026-11-06: "found on the Polish market")."""
    origin = _Origin(make, market, official, trusted)
    models, used = _supported(entries, docs, market)
    priced_market = european(market)
    if not any(origin.official_page(u) or priced or (not priced_market and origin.trusted_page(u))
               for u, (_, priced) in used.items()):  # fmt: skip
        return Lineup(make=make)
    sources = [{"url": u, "name": name, "type": "MANUFACTURER" if origin.official_page(u) else "PUBLICATION"}
               for u, (name, _) in used.items()]  # fmt: skip
    return Lineup(make=make, models=models, sources=sources, fetched_at=datetime.now(UTC))


async def cached(make: str, ttl_days: int, market: str = "ES") -> Lineup | None:
    """The make's line-up on the market as cached, None when there is none younger than `ttl_days`."""
    row = await acquisition.cached_lineup(make, market, ttl_days)
    if row is None:
        return None
    models = [LineupModel(model=m["model"], body=m.get("body", ""), powertrains=tuple(m.get("powertrains") or ()),
                          price_from_eur=m.get("price_from_eur"), source_url=m.get("source_url"),
                          country=m.get("country")) for m in row.models]  # fmt: skip
    return Lineup(make=make, models=models, sources=list(row.sources), fetched_at=row.fetched_at)


async def store(lu: Lineup, market: str = "ES") -> None:
    """Cache the line-up for the market (replacing the one cached before)."""
    models = [{"model": m.model, "body": m.body, "powertrains": list(m.powertrains),
               "price_from_eur": m.price_from_eur, "source_url": m.source_url, "country": m.country}
              for m in lu.models]  # fmt: skip
    await acquisition.store_lineup(StoredLineup(make=lu.make, market=market, models=models, sources=lu.sources,
                                                fetched_at=lu.fetched_at))  # fmt: skip


async def get_lineup(ports: Ports, make: str, market: str = "ES") -> Lineup | None:
    """The make's line-up in Spain, or on `market` for a car not sold in Spain (cache-first), or None when no source
    supports one."""
    lim = ports.ref.search["intake"]
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


def _supported(entries: list[LineupEntry], docs: dict[str, tuple[str, str]],
               market: str) -> tuple[list[LineupModel], dict[str, tuple[str, bool]]]:  # fmt: skip
    """The models their documents support (first spelling wins) and the sources used: url -> (title, priced)."""
    priced_market = european(market)
    out: list[LineupModel] = []
    used: dict[str, tuple[str, bool]] = {}
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
        if price is not None and not _price_supported(price, e.excerpt, text):
            price = None
        seen.add(name.lower())
        pts = tuple(p for p in (x.lower() for x in e.powertrains) if p in POWERTRAINS)
        country = country_of_url(e.source_url) if market != "ES" and priced_market else None
        out.append(LineupModel(model=name, body=e.body.lower(), powertrains=pts, price_from_eur=price,
                               source_url=e.source_url, country=country))  # fmt: skip
        used[e.source_url] = (title or e.source_url, price is not None)
    return out, used


def _price_supported(price: int, excerpt: str, text: str) -> bool:
    """In range, written in the excerpt, and the excerpt in the document."""
    lo, hi = PRICE_RANGE
    return lo <= price <= hi and str(price) in _NOT_DIGIT.sub("", excerpt) and evidence.occurs(excerpt, text)
