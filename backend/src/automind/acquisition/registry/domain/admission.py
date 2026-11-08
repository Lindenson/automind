"""Admission check of a site met in a search (spec 010 US7, FR-019). Pure: the facts are gathered elsewhere.

Order: deny-list and classifieds → robots for the sample path → the terms of use (a forbidding clause must be
quoted from the page) → readable content. A site we could not judge stays `unknown` (no slots) until a re-check.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from automind.acquisition.registry.domain.seed_rules import denied

CLASSIFIEDS_WORDS = ("anuncios", "classifieds", "kleinanzeigen", "annonces", "annunci", "segunda mano particulares")
MIN_CONTENT_CHARS = 800


@dataclass(frozen=True)
class AdmissionFacts:
    """What was gathered about a site: robots, the terms of use, readable content, the title."""

    domain: str
    robots_allows: bool | None  # None: not checked (network error)
    terms_forbid: bool | None  # None: no terms page found or not judged
    clause: str | None = None  # the forbidding clause, verified to occur on the terms page
    terms_url: str | None = None
    content_chars: int | None = None
    title: str = ""


@dataclass(frozen=True)
class Admission:
    """The verdict: the access, why, and the evidence kept with it."""

    access: str  # ok | classifieds | robots_blocked | terms_forbid | js_only | unknown
    reason: str
    evidence: dict[str, str]


def admit(f: AdmissionFacts, deny: Sequence[str]) -> Admission:
    """The access of a site from its facts, in the order of the module docstring."""
    if denied(f.domain, deny) or any(w in f.title.lower() for w in CLASSIFIEDS_WORDS):
        return Admission("classifieds", "classifieds or deny-listed site", {"rule": "deny-list / classifieds"})
    if f.robots_allows is False:
        return Admission("robots_blocked", "robots.txt disallows reading the sample page", {"rule": "robots.txt"})
    if f.terms_forbid is True and f.clause:
        return Admission(
            "terms_forbid",
            "the terms of use forbid automated access",
            {"clause": f.clause[:500], "url": f.terms_url or ""},
        )
    if f.content_chars is not None and f.content_chars < MIN_CONTENT_CHARS:
        return Admission("js_only", "the page has no readable text without JavaScript", {"chars": str(f.content_chars)})
    if f.robots_allows is None or f.terms_forbid is None:
        return Admission("unknown", "not enough facts to admit (robots or terms not checked)", {})
    return Admission(
        "ok",
        "robots allow it and the terms do not forbid automated reading",
        {"url": f.terms_url or "", "clause": f.clause or ""},
    )
