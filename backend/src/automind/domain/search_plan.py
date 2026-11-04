"""Search plan (spec 003 FR-002, FR-003; research R2). Pure.

Round 0 queries the favourite sites of the area for each market, grouped into `site:a OR site:b`
queries in priority order (the official manufacturer site first when one is given). Later rounds use
the open-web templates. Deny-listed sites never appear. Queries are built by code, never by an AI.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, Literal

from automind.domain.evidence import is_denied

Kind = Literal["FAVOURITE", "FAVOURITE_RETRY", "OPEN", "AI"]


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
    learned: bool = False


# --- short identity for favourite queries (spec 007 FR-020; chat 757cff3d) -----------------------------------
# A `site:a OR site:b` query needs every word on the page. Pages never write "Mk8.5" or "G21", rarely the
# gearbox, and the variant name often repeats the model ("Golf Variant R"), so long queries found nothing.

# Mk8.5, chassis codes like G21 or F30 (one capital + two digits), and decimals that are not displacements
_GEN_CODE = re.compile(r"^(?:[Mm][Kk]\d+(?:\.\d)?|[A-Z]\d{2}|\d\.\d)$")
_NOISE = {
    "dsg", "s-tronic", "stronic", "steptronic", "tiptronic", "automatic", "automático", "automatico", "auto",
    "manual", "cvt", "e-cvt", "edc", "eat8", "eat6", "8dct", "7dct", "dct", "at", "mt", "4motion", "xdrive",
    "quattro", "awd", "4wd", "4x4", "2wd", "fwd", "rwd", "cv", "ps", "hp", "kw", "bhp", "pk", "kwh", "6v",
    "8-speed", "7-speed", "6-speed", "speed", "/", "-", "+",
}  # fmt: skip
_ENGINE_CODE = re.compile(r"^m?\d{3}(?:d|i|e|xe|xd|li|td|is)$", re.I)  # 320d, 520i, 330e, m340i, 225xe
_BODY = {"touring", "variant", "avant", "sportback", "estate", "sw", "kombi", "sportstourer", "sports", "tourer",
         "cabrio", "coupé", "coupe", "shooting", "brake", "fastback", "sportswagon"}  # fmt: skip
_TRIM = re.compile(r"^(?:r|gti|gtd|gte|n|rs\d{0,2}|s\d|st|amg|cupra|vrs|performance|type|m|sti|nismo|gr)$", re.I)
_DISPLACEMENT = re.compile(r"^[0-6]\.\d$")
_POWER = re.compile(r"^\d{2,4}$")
_TECH = re.compile(r"^(?:[a-z]+-)?[a-z]*(?:tsi|tdi|tfsi|ecotsi|vtec|gdi|t-gdi|crdi|puretech|bluehdi|d-4d|skyactiv|"
                   r"hybrid|híbrido|mhev|phev|hev|e-hybrid|ecoboost|tce|dci|mild|dm-i|dm-p|e:hev|e-tech|e-power)"
                   r"[a-z-]*$", re.I)  # fmt: skip
_FUEL = re.compile(r"^(?:hybrid|híbrido|mhev|phev|hev|e-hybrid|electric|eléctrico|diesel|mild)$", re.I)


_MODEL_FROM_CODE = {"bmw"}  # makes whose engine code names the model on its own ("320d" is a 3 Series)


def short_identity(car: Identity, level: int = 0) -> str:
    """Make + model + a short variant key (code, pure). Level 1 is the shorter retry form.

    The key is an engine code ("320d"; for BMW it names the model on its own), else a named trim with its power
    ("Variant R 333", "GTI 245"), else displacement + technology + power ("1.5 EcoTSI 150"). Generation codes,
    gearbox and drive words and words already in make or model are dropped; the key keeps the page's word order
    ("35 TFSI")."""
    own = {w.lower() for w in f"{car.make} {car.model}".split()}
    gen = {w.lower() for w in (car.generation or "").replace("(", " ").replace(")", " ").split()}
    toks = [t for t in re.split(r"[\s,()]+", car.variant) if t]

    def wanted(t: str) -> bool:
        low = t.lower()
        if low in own or low in gen or low in _NOISE:
            return False
        return bool(_DISPLACEMENT.match(t)) or not _GEN_CODE.match(t)

    keep = [t for t in toks if wanted(t)]
    head = f"{car.make} {car.model}"
    code = next((t for t in keep if _ENGINE_CODE.match(t)), None)
    if code:
        lead = car.make if car.make.lower() in _MODEL_FROM_CODE else head
        if level:
            return f"{lead} {code}"
        return f"{lead} " + " ".join(_dedup_key([t for t in keep if t == code or t.lower() in _BODY], own))
    if level:
        return head
    power = next((t for t in keep if _POWER.match(t)), None)
    trim = [t for t in keep if _TRIM.match(t)]
    if trim:
        chosen = {*trim, *(t for t in keep if t.lower() in _BODY), *([power] if power else [])}
    else:
        disp = next((t for t in keep if _DISPLACEMENT.match(t)), None)
        tech = [t for t in keep if _TECH.match(t) and t != disp][:1]
        fuel = [t for t in keep if _FUEL.match(t) and t not in tech][:1]
        chosen = {*([disp] if disp else []), *tech, *([power] if power else []), *fuel}
        if power and not disp and not tech:  # "E 250 d": the class letter before the number
            i = keep.index(power)
            if i > 0 and len(keep[i - 1]) == 1 and keep[i - 1].isalpha():
                chosen.add(keep[i - 1])
        if not chosen:
            chosen = {t for t in keep if not _POWER.match(t)}
            chosen = set(sorted(chosen, key=keep.index)[:2])
    key = [t for t in keep if t in chosen]
    return " ".join([head, *_dedup_key(key, own)]).strip()


def _dedup_key(words: list[str], own: set[str]) -> list[str]:
    seen = set(own)
    out = []
    for w in words:
        if w.lower() not in seen:
            seen.add(w.lower())
            out.append(w)
    return out


def _render(template: str, car: Identity, sites: Sequence[str] = (), level: int = 0) -> str:
    text = template.format(
        short=short_identity(car, level),
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
    learned: Mapping[str, Sequence[str]] | None = None,
    learned_per_area: int = 4,
) -> list[PlannedQuery]:
    out: list[PlannedQuery] = []
    seen_text: set[str] = set()

    def add(q: PlannedQuery) -> None:
        if q.text and q.text not in seen_text:
            seen_text.add(q.text)
            out.append(q)

    if round_ == 0:
        if not favourite_templates.get(area):
            return out
        used: set[str] = set()
        for market in dict.fromkeys(markets):  # keep order, drop duplicates
            # the market's own words when configured ("reliability@DE": Pannenstatistik, TÜV-Report)
            template = favourite_templates.get(f"{area}@{market}") or favourite_templates[area]
            sites = favourite_sites(area, market, favourites)
            official = manufacturer_site and market == "ES" and area in ("price", "specs", "maintenance")
            if official and manufacturer_site and not is_denied(f"https://{manufacturer_site}/"):
                sites = [manufacturer_site, *sites]
            sites = [s for s in dict.fromkeys(sites) if s not in used]
            used.update(sites)
            for i in range(0, len(sites), max(1, sites_per_query)):
                group = tuple(sites[i : i + sites_per_query])
                add(PlannedQuery(_render(template, car, group), "FAVOURITE", area, market, group))
            # learned sources (FR-022): after the configured ones, never denied, never twice
            extra = [d for d in dict.fromkeys((learned or {}).get(market, ()))
                     if d not in used and not is_denied(f"https://{d}/")][: max(0, learned_per_area)]  # fmt: skip
            used.update(extra)
            for i in range(0, len(extra), max(1, sites_per_query)):
                group = tuple(extra[i : i + sites_per_query])
                add(PlannedQuery(_render(template, car, group), "FAVOURITE", area, market, group, learned=True))
        return out
    first_market = markets[0] if markets else "ES"
    for t in open_templates.get(area, ()):
        add(PlannedQuery(_render(t, car), "OPEN", area, first_market))
    return out


ELECTRIC = ("BEV", "PHEV", "EREV")


def ev_queries(base: Sequence[PlannedQuery], car: Identity, powertrain: str | None,
               templates: Mapping[str, str]) -> list[PlannedQuery]:  # fmt: skip
    """Extra favourite queries for electric facts (spec 006 R10): range, kWh/100 km, charging; for plug-ins the
    consumption with an empty battery. One per area and template, on the first group of favourite sites."""
    pt = (powertrain or "").upper()
    if pt not in ELECTRIC:
        return []
    keys = ["ev"] + (["cs"] if pt != "BEV" else [])
    out: list[PlannedQuery] = []
    seen = {q.text for q in base}
    for q in base:
        if q.kind != "FAVOURITE" or q.learned:
            continue
        for k in keys:
            t = templates.get(f"{q.area}_{k}@{q.market}") or templates.get(f"{q.area}_{k}")
            text = _render(t, car, q.sites) if t else ""
            if text and text not in seen:
                seen.add(text)
                out.append(replace(q, text=text))
        break  # the first group of sites only: one extra search per template
    return out


def retry_queries(
    empty: Sequence[PlannedQuery], car: Identity, favourite_templates: Mapping[str, str]
) -> list[PlannedQuery]:
    """One shorter retry per favourite query that found nothing (FR-021). A retry is never retried."""
    out: list[PlannedQuery] = []
    for q in empty:
        if q.kind != "FAVOURITE":
            continue
        template = favourite_templates.get(f"{q.area}@{q.market}") or favourite_templates.get(q.area)
        if not template:
            continue
        text = _render(template, car, q.sites, level=1)
        if text != q.text and text not in {o.text for o in out}:
            out.append(replace(q, text=text, kind="FAVOURITE_RETRY"))
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
