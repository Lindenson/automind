"""Learned sources (spec 007 US5, FR-022). Pure.

A domain whose values were accepted in several research runs becomes a round-0 source for that area and market,
after the configured favourites. It expires when it keeps giving nothing. It is only a search hint: its pages pass
the same relevance, excerpt and sense checks, and its authority comes from `classify_source` (so a fan club or a
look-alike brand domain is never MANUFACTURER). Deny-listed domains are never used.

No self-reinforcement (spec 007 J, T078): a learned domain is searched first, so it finds accepted values more
often. Only an acceptance of a page that a normal (not learned) query also found counts as a new run and clears
the misses; an acceptance through the domain's own learned query is neutral. Pages that did not come from a
search (e.g. a URL the user pasted) never count.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

from automind.domain.evidence import classify_source, domain_of, is_denied


@dataclass(frozen=True)
class Config:
    min_runs: int = 3
    max_misses: int = 5
    per_area: int = 4

    @classmethod
    def from_mapping(cls, m: Mapping[str, Any] | None) -> Config:
        m = m or {}
        return cls(int(m.get("min_runs", 3)), int(m.get("max_misses", 5)), int(m.get("per_area", 4)))


@dataclass(frozen=True)
class LearnedRow:
    domain: str
    area: str
    market: str
    source_type: str
    accepted_runs: int = 0
    misses: int = 0


def domain_key(url: str) -> str:
    return domain_of(url)


def source_type_of(url: str) -> str:
    return classify_source(url)


def update_row(row: LearnedRow, *, accepted: bool, independent: bool = True) -> LearnedRow:
    if accepted and independent:
        return replace(row, accepted_runs=row.accepted_runs + 1, misses=0)
    if accepted:  # found only through its own learned query: keeps it, proves nothing new
        return row
    return replace(row, misses=row.misses + 1)


def is_active(row: LearnedRow, cfg: Config, *, favourites: set[str]) -> bool:
    return (
        row.accepted_runs >= cfg.min_runs
        and row.misses < cfg.max_misses
        and row.domain not in favourites
        and not is_denied(f"https://{row.domain}/")
    )
