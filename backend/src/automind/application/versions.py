"""Versions of a model generation sold in Spain, with sources: the input of the identification ladder
(domain/ladder.py, spec 008 US6).

Cache-first (the `versions` port: table `model_versions`, shared by every chat, refreshed after
`intake.versions_ttl_days`). On a miss: one Spanish search for the model and the year (or generation),
≤ `intake.versions_max_pages` pages through the page store (robots respected, deny-list never read), the `versions`
web reader extracts, and code keeps only what the documents support (FR-017): the power of each version is written
in its excerpt, the excerpt occurs in its document, and its years overlap the generation's.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from automind.application.ports import Ports
from automind.application.usage import current_budget
from automind.domain import evidence, identity
from automind.domain.ladder import Generation, Version

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


async def lookup(ports: Ports, make: str, model: str, *, generation: str | None, year: int | None,
                 new: bool) -> Generation | None:  # fmt: skip
    """The versions of this model in the generation asked (or the one built in `year`, or on sale now); None when
    there is no store or no document supports any version (the fallback identifies then, FR-020)."""
    store = ports.versions
    if store is None or "versions" not in (ports.ref.prompts or {}):
        return None
    lim = _limits(ports)
    if (hit := await store.get(make, model, generation, year, new, int(lim.get("versions_ttl_days", 60)))) is not None:
        return hit  # type: ignore[no-any-return]
    when = generation or (str(year) if year else "nuevo")
    budget = current_budget.get()
    before = budget.search_calls if budget is not None else 0
    try:
        hits = await ports.search.search(f"{make} {model} {when} versiones motores potencia CV ficha técnica",
                                         market="ES", area="specs")  # fmt: skip
        docs: dict[str, tuple[str, str]] = {}
        for h in hits[:8]:
            if len(docs) >= int(lim.get("versions_max_pages", 3)):
                break
            if evidence.is_denied(h.url):
                continue
            page = await ports.page_store.get(h.url, area="specs")
            if page and page.text:
                docs[page.url] = (page.title or "", page.text[:14000])
    finally:
        if budget is not None:  # identification, not research: counted apart (the turn's research needs consent)
            budget.identify_search_calls += budget.search_calls - before
    if not docs:
        return None
    blob = "\n\n".join(f'<untrusted_document url="{u}">\n{t}\n{x[:7000]}\n</untrusted_document>'
                       for u, (t, x) in docs.items())  # fmt: skip
    ask = (f"Make: {make}\nModel: {model}\n" + (f"Generation: {generation}\n" if generation else "")
           + (f"Year built: {year}\n" if year else "Bought new now.\n") + f"\n{blob}")  # fmt: skip
    out = await ports.llm.structured("versions", VersionsOut, ports.ref.prompts["versions"], ask)
    kept = validate(out, docs)
    gen = generation or out.generation
    if not kept or not gen:
        return None
    srcs = [{"url": u, "name": t or u} for u, (t, _) in docs.items() if any(v.source_url == u for v in kept)]
    g = Generation(make, model, gen, out.generation_years_from, out.generation_years_to, out.body_class, kept, srcs)
    await store.put(g)
    return g
