"""How the registry starts (spec 010 US8): favourites, the 009 survey and the learned domains. Pure."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from .model import Capability, Source

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


def market_of(country: Any) -> str:
    code = re.match(r"[A-Z]{2}", str(country or "")) if country else None
    if not code:
        return "ANY"
    return MARKET_OF_COUNTRY.get(code.group(0), "ANY" if code.group(0) == "EU" else code.group(0))


def denied(domain: str, deny: Sequence[str]) -> bool:
    d = domain.lower().removeprefix("www.")
    return any(d == x or d.endswith("." + x) for x in deny)


def _clause(text: str) -> str:
    return text.strip().strip("'\"")[:500]


def from_survey(
    e: Mapping[str, Any], deny: Sequence[str], families: Mapping[str, Sequence[str]] | None = None
) -> tuple[Source, list[Capability]]:
    from .families import family_of  # noqa: PLC0415

    domain = str(e["domain"]).lower().removeprefix("www.")
    access, status = VERDICT.get(str(e.get("verdict")), ("unknown", "candidate"))
    if denied(domain, deny) or e.get("classifieds"):
        access, status = "classifieds", "blocked"
    evidence = {
        k: v
        for k, v in {
            "robots": e.get("robots"),
            "clause": _clause(str(e.get("tos") or "")) or None,
            "sample_url": e.get("sample_url"),
            "survey": e.get("survey"),
            "rule": "deny-list" if access == "classifieds" else None,
        }.items()
        if v
    }
    market = market_of(e.get("country"))
    src = Source(
        domain=domain,
        source_type="PUBLICATION",
        family=family_of(domain, families or {}),
        markets=[market],
        languages=[str(e["lang"])] if e.get("lang") else [],
        access=access,
        access_evidence=evidence,
        checked_at=str(e.get("checked") or "") or None,
    )
    areas = sorted({AREA_OF_KIND.get(k, k) for k in e.get("kinds") or []})
    return src, [Capability(domain, a, market, status) for a in areas]


def from_favourite(
    f: Mapping[str, Any], deny: Sequence[str], families: Mapping[str, Sequence[str]] | None = None
) -> tuple[Source, list[Capability]]:
    from .families import family_of  # noqa: PLC0415

    domain = str(f["domain"]).lower()
    blocked = denied(domain, deny)
    src = Source(
        domain=domain,
        source_type=str(f.get("source_type") or "PUBLICATION"),
        family=family_of(domain, families or {}),
        markets=list(f.get("markets") or ["ANY"]),
        access="classifieds" if blocked else "ok",
        reader=f.get("reader"),
        checked_at=str(f.get("tos_checked")) if f.get("tos_checked") else None,
    )
    caps = [
        Capability(domain, str(a), str(m), "blocked" if blocked else "active", int(f.get("priority", 3)))
        for a in f.get("areas") or []
        for m in f.get("markets") or ["ANY"]
    ]
    return src, caps


def from_learned(row: Mapping[str, Any], deny: Sequence[str], min_runs: int = 3, max_misses: int = 5) -> Capability:
    domain = str(row["domain"]).lower()
    ok = int(row.get("accepted_runs") or 0) >= min_runs and int(row.get("misses") or 0) < max_misses
    status = "blocked" if denied(domain, deny) else "active" if ok else "candidate"
    runs = float(row.get("accepted_runs") or 0)
    return Capability(
        domain,
        str(row["area"]),
        str(row["market"]),
        status,
        None,
        attempts=runs + float(row.get("misses") or 0),
        accepted=runs,
    )
