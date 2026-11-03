"""Brand line-up lookup (spec 005 R2, FR-007, FR-008, FR-011): the models of a make on sale in Spain, with sources.

Cache-first (`brand_lineups`, refreshed after `intake.lineup_ttl_days`). On a miss: one Spanish search plus the
official site, ≤ `lineup_max_pages` pages read through the page store (robots respected, deny-list never read), the
`lineup` web reader extracts, and code keeps only what the documents support:
- a model must be written in the text of its document;
- a price must be written in its excerpt, and the excerpt in the document;
- at least one source must be the official site or a page that states a price (otherwise nothing is stored).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select

from automind.application.ports import Ports
from automind.domain import evidence
from automind.domain.intake import LineupModel
from automind.infrastructure import db


class _Entry(BaseModel):
    model: str
    body: str = ""
    powertrains: list[str] = Field(default_factory=list)
    price_from_eur: int | None = None
    excerpt: str = ""
    source_url: str = ""


class LineupOut(BaseModel):
    models: list[_Entry] = Field(default_factory=list)


@dataclass
class Lineup:
    make: str
    models: list[LineupModel] = field(default_factory=list)
    sources: list[dict[str, Any]] = field(default_factory=list)
    fetched_at: datetime | None = None


_PTS = {"petrol", "diesel", "hybrid", "mhev", "phev", "bev", "lpg"}


def _limits(ports: Ports) -> dict[str, Any]:
    return dict(ports.ref.search.get("intake") or {})


def _price_in(excerpt: str, price: int) -> bool:
    digits = re.sub(r"\D", "", excerpt)
    return str(price) in digits


def validate(make: str, entries: list[_Entry], docs: dict[str, tuple[str, str]], official: str | None) -> Lineup:
    """Keep the entries their documents support (pure apart from the evidence helpers)."""
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
        price = e.price_from_eur
        if price is not None and not (5000 <= price <= 500000 and _price_in(e.excerpt, price)
                                      and evidence.occurs(e.excerpt, text)):  # fmt: skip
            price = None
        seen.add(name.lower())
        pts = tuple(p for p in (x.lower() for x in e.powertrains) if p in _PTS)
        out.append(LineupModel(model=name, body=e.body.lower(), powertrains=pts, price_from_eur=price,
                               source_url=e.source_url))  # fmt: skip
        used[e.source_url] = {"url": e.source_url, "name": title or e.source_url, "priced": price is not None}
    dom = official.split("/")[0].removeprefix("www.") if official else None

    def _official(u: str) -> bool:  # the host itself, never a substring (nicebyd.com is not byd.com)
        d = evidence.domain_of(u)
        return bool(dom) and (d == dom or d.endswith("." + dom))

    ok = any(_official(u) or src["priced"] for u, src in used.items())
    if not ok:
        return Lineup(make=make)
    srcs = [{"url": s["url"], "name": s["name"], "type": "MANUFACTURER" if _official(s["url"]) else "PUBLICATION"}
            for s in used.values()]  # fmt: skip
    return Lineup(make=make, models=out, sources=srcs, fetched_at=datetime.now(UTC))


def _row_of(make: str) -> Any:
    return select(db.BrandLineup).where(db.BrandLineup.make == make, db.BrandLineup.market == "ES")


async def cached(make: str, ttl_days: int) -> Lineup | None:
    async with db.sessionmaker()() as s:
        row = (await s.execute(_row_of(make))).scalar_one_or_none()
    if row is None or row.fetched_at < datetime.now(UTC) - timedelta(days=ttl_days):
        return None
    models = [LineupModel(model=m["model"], body=m.get("body", ""), powertrains=tuple(m.get("powertrains") or ()),
                          price_from_eur=m.get("price_from_eur"), source_url=m.get("source_url"))
              for m in row.models]  # fmt: skip
    return Lineup(make=make, models=models, sources=list(row.sources), fetched_at=row.fetched_at)


async def store(lu: Lineup) -> None:
    models = [{"model": m.model, "body": m.body, "powertrains": list(m.powertrains),
               "price_from_eur": m.price_from_eur, "source_url": m.source_url} for m in lu.models]  # fmt: skip
    async with db.sessionmaker()() as s:
        row = (await s.execute(_row_of(lu.make))).scalar_one_or_none()
        if row is None:
            row = db.BrandLineup(make=lu.make, market="ES")
            s.add(row)
        row.models, row.sources, row.fetched_at = models, lu.sources, lu.fetched_at or datetime.now(UTC)
        await s.commit()


async def get_lineup(ports: Ports, make: str) -> Lineup | None:
    """The make's line-up in Spain (cache-first), or None when no source supports one."""
    lim = _limits(ports)
    if (hit := await cached(make, int(lim.get("lineup_ttl_days", 30)))) is not None:
        return hit
    reg = ports.ref.makes
    official = reg.site(make) if reg is not None else None
    hits = await ports.search.search(f"{make} gama modelos precios España", market="ES", area="price")
    urls = [f"https://www.{official}" if official else None] + [h.url for h in hits[:4]]
    docs: dict[str, tuple[str, str]] = {}
    for u in [x for x in urls if x and not evidence.is_denied(x)]:
        if len(docs) >= int(lim.get("lineup_max_pages", 2)):
            break
        page = await ports.page_store.get(u, area="price")
        if page and page.text:
            docs[page.url] = (page.title or "", page.text[:12000])
    if not docs:
        return None
    blob = "\n\n".join(f'<untrusted_document url="{u}">\n{t}\n{x[:6000]}\n</untrusted_document>'
                       for u, (t, x) in docs.items())  # fmt: skip
    out = await ports.llm.structured("lineup", LineupOut, ports.ref.prompts["lineup"], f"Make: {make}\n\n{blob}")
    lu = validate(make, out.models, docs, official)
    if not lu.models:
        return None
    await store(lu)
    return lu
