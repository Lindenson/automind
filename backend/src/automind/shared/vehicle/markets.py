"""Markets where a car is sold when not in Spain: Europe, the make home market, anywhere; the country of a URL; the
notes shown for a car from abroad (chat 2026-11-06)."""

from __future__ import annotations

import re

EUROPE = "EU"  # the European markets as one (spec 009 FR-009)


ANYWHERE = "ANY"


# geographic Europe as one market (owner 2026-11-06): the EU, the UK, Switzerland, Norway, Iceland, the Balkans,
# Ukraine, Moldova, Turkey — no country preferred
EUROPEAN_COUNTRIES = frozenset({"ES", "DE", "FR", "IT", "PT", "NL", "BE", "LU", "AT", "CH", "IE", "GB", "SE", "DK",
                                "NO", "FI", "IS", "PL", "CZ", "SK", "HU", "SI", "HR", "RO", "BG", "GR", "CY", "MT",
                                "EE", "LV", "LT", "RS", "BA", "ME", "MK", "AL", "XK", "UA", "MD", "TR"})  # fmt: skip


EUROPEAN = EUROPEAN_COUNTRIES | {EUROPE, "EN", "UK"}


_TLD = {"uk": "GB", "gr": "GR", "si": "SI"}  # a top-level domain that is not the country code


def country_of_url(url: str | None) -> str | None:
    """The European country a page is for, by its country domain (deepal.pl → PL, autoexpress.co.uk → GB); None
    for .com, .eu and the like."""
    host = re.sub(r"^[a-z]+://", "", (url or "").lower()).split("/", 1)[0].split(":", 1)[0]
    tld = host.rsplit(".", 1)[-1] if "." in host else ""
    code = _TLD.get(tld, tld.upper())
    return code if code in EUROPEAN_COUNTRIES else None


def lookup_markets(home: str | None) -> list[str]:
    """Where a car missing from the Spanish line-up is looked up, in order: Europe first, then the market its make
    comes from, then anywhere."""
    out = [EUROPE]
    if home and home.upper() not in EUROPEAN and home.upper() != ANYWHERE:
        out.append(home.upper())
    out.append(ANYWHERE)
    return out


def european(market: str | None) -> bool:
    """A car of this market is priced from its own sources (None: Spain); outside Europe no price is ever taken
    (spec 009 FR-009: prices come from European markets only)."""
    return market is None or market.upper() in EUROPEAN


def market_note(market: str | None) -> str:
    """The phrase that says where a car not sold in Spain was found: in Europe (its data and prices from there) or
    outside it (data from there, prices from Europe only)."""
    return "sold_in_europe" if european(market) else "sold_abroad"


def abroad_note(market: str | None, priced: bool) -> str | None:
    """What the report says about a car not sold in Spain (a phrase key): found on a European market, where it was
    found; outside Europe, that its data come from there and its price only from a European source — and when there
    is none, that no euro price is given (FR-009). None for a car sold in Spain."""
    if market is None:
        return None
    if european(market):
        return "sold_in_europe"
    return "abroad_priced" if priced else "abroad_no_price"
