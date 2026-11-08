"""How the registry starts (spec 010 US8): favourites and the 009 survey. Pure."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from automind.acquisition.registry.domain.families import family_of
from automind.acquisition.registry.domain.model import Capability, Source
from automind.shared.contracts.json import JsonObject

AREA_OF_KIND = {
    "specs": "specs",
    "new_price": "price",
    "used_price": "used_price",
    "measured": "measured",
    "reliability": "reliability",
    "owner_reviews": "reviews",
    "consumption_real": "specs",
    "phev_ev_consumption": "specs",
    "used_issues": "used_issues",
    "maintenance": "maintenance",
    "residual_value": "depreciation",
    "recalls": "used_issues",
    "safety": "specs",
    "warranty": "manufacturer",
}
MARKET_OF_COUNTRY = {
    "GB": "EN",
    "IE": "EN",
    "US": "EN",
    "AT": "DE",
    "CH": "DE",
    "DE": "DE",
    "ES": "ES",
    "FR": "FR",
    "BE": "FR",
    "IT": "IT",
    "PT": "PT",
    "NL": "NL",
}
VERDICT = {  # survey verdict -> (access, capability status)
    "candidate": ("ok", "candidate"),
    "classifieds": ("classifieds", "blocked"),
    "tos_forbids": ("terms_forbid", "blocked"),
    "blocked_robots": ("robots_blocked", "blocked"),
    "paywall": ("paywall", "retired"),
    "js_only": ("js_only", "retired"),
    "dead": ("dead", "retired"),
}
COUNTRY = re.compile(r"[A-Z]{2}")
CLAUSE_CHARS = 500


@dataclass(frozen=True)
class SurveyEntry:
    """One site of the 009 survey (`config/registry_seed_survey.yaml`) as the seed reads it."""

    domain: str
    verdict: str = ""
    classifieds: bool = False
    kinds: tuple[str, ...] = ()
    country: str | None = None
    lang: str | None = None
    robots: str | None = None
    tos: str = ""
    sample_url: str | None = None
    survey: str | None = None
    checked: str | None = None

    @classmethod
    def from_mapping(cls, e: JsonObject) -> SurveyEntry:
        """Read one YAML entry (a terms quote given as a mapping is kept as its text)."""
        return cls(
            domain=str(e["domain"]), verdict=str(e.get("verdict")), classifieds=bool(e.get("classifieds")),
            kinds=tuple(str(k) for k in e.get("kinds") or []), country=_text(e.get("country")),
            lang=_text(e.get("lang")), robots=_text(e.get("robots")), tos=str(e.get("tos") or ""),
            sample_url=_text(e.get("sample_url")), survey=_text(e.get("survey")), checked=_text(e.get("checked")),
        )  # fmt: skip


@dataclass(frozen=True)
class Favourite:
    """One favourite of `config/sources.yaml` as the seed reads it."""

    domain: str
    source_type: str = "PUBLICATION"
    areas: tuple[str, ...] = ()
    markets: tuple[str, ...] = ("ANY",)
    priority: int = 3
    reader: str | None = None
    tos_checked: str | None = None

    @classmethod
    def from_mapping(cls, f: JsonObject) -> Favourite:
        """Read one YAML entry."""
        return cls(
            domain=str(f["domain"]), source_type=str(f.get("source_type") or "PUBLICATION"),
            areas=tuple(str(a) for a in f.get("areas") or []),
            markets=tuple(str(m) for m in f.get("markets") or ["ANY"]), priority=int(f.get("priority", 3)),
            reader=_text(f.get("reader")), tos_checked=_text(f.get("tos_checked")),
        )  # fmt: skip


def market_of(country: str | None) -> str:
    """The registry market of a survey country ("GB" → "EN", "EU" → "ANY"); "ANY" when there is no country code."""
    code = COUNTRY.match(country) if country else None
    if not code:
        return "ANY"
    return MARKET_OF_COUNTRY.get(code.group(0), "ANY" if code.group(0) == "EU" else code.group(0))


def denied(domain: str, deny: Sequence[str]) -> bool:
    """The domain or a parent domain is on the deny-list."""
    d = domain.lower().removeprefix("www.")
    return any(d == x or d.endswith("." + x) for x in deny)


def from_survey(
    e: SurveyEntry, deny: Sequence[str], families: Mapping[str, Sequence[str]] | None = None
) -> tuple[Source, list[Capability]]:
    """The source and its capabilities from a survey entry: the verdict gives access and status, the deny-list and
    a classifieds flag block it; one capability per area of its kinds on its market."""
    domain = e.domain.lower().removeprefix("www.")
    access, status = VERDICT.get(e.verdict, ("unknown", "candidate"))
    if denied(domain, deny) or e.classifieds:
        access, status = "classifieds", "blocked"
    evidence = {
        k: v
        for k, v in {
            "robots": e.robots,
            "clause": _clause(e.tos) or None,
            "sample_url": e.sample_url,
            "survey": e.survey,
            "rule": "deny-list" if access == "classifieds" else None,
        }.items()
        if v
    }
    market = market_of(e.country)
    src = Source(
        domain=domain,
        source_type="PUBLICATION",
        family=family_of(domain, families or {}),
        markets=[market],
        languages=[e.lang] if e.lang else [],
        access=access,
        access_evidence=evidence,
        checked_at=e.checked,
    )
    areas = sorted({AREA_OF_KIND.get(k, k) for k in e.kinds})
    return src, [Capability(domain, a, market, status) for a in areas]


def from_favourite(
    f: Favourite, deny: Sequence[str], families: Mapping[str, Sequence[str]] | None = None
) -> tuple[Source, list[Capability]]:
    """The source and its active capabilities (seed priority = its priority) for every area and market; a
    deny-listed favourite is blocked."""
    domain = f.domain.lower()
    blocked = denied(domain, deny)
    src = Source(
        domain=domain,
        source_type=f.source_type,
        family=family_of(domain, families or {}),
        markets=list(f.markets),
        access="classifieds" if blocked else "ok",
        reader=f.reader,
        checked_at=f.tos_checked,
    )
    caps = [
        Capability(domain, a, m, "blocked" if blocked else "active", f.priority) for a in f.areas for m in f.markets
    ]
    return src, caps


def _text(value: object) -> str | None:
    return str(value) if value else None


def _clause(text: str) -> str:
    return text.strip().strip("'\"")[:CLAUSE_CHARS]
