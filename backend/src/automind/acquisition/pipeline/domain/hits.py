"""Accepted evidence per source domain for an area — the input to the section minimum (spec 002 FR-020). A source
read from a registry candidate is marked `unverified` and counts half (spec 011 FR-022)."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from automind.shared.contracts.json import JsonObject


class SourceKind(StrEnum):
    """Where an area's accepted values are stored."""

    CLAIMS = "claims"  # spec claims
    MAINTENANCE = "maintenance"  # claims and the service schedule
    MANUFACTURER = "manufacturer"  # brand facts
    ITEMS = "items"  # the area's own items (reviews, issues, used prices, value retention)


@dataclass(frozen=True)
class SourceRef:
    """The source of one accepted value: its domain, its type and whether a registry candidate gave it."""

    domain: str
    source_type: str
    unverified: bool


def source_kind(area: str, spec_areas: Sequence[str]) -> SourceKind:
    """Where an area's accepted values are stored: spec claims, claims and schedule, brand facts, or area items."""
    if area in spec_areas:
        return SourceKind.CLAIMS
    if area == SourceKind.MAINTENANCE:
        return SourceKind.MAINTENANCE
    return SourceKind.MANUFACTURER if area == SourceKind.MANUFACTURER else SourceKind.ITEMS


def hits_of(sources: Sequence[SourceRef]) -> list[JsonObject]:
    """One hit per (domain, type, unverified) with the number of values it gave, in first-seen order."""
    counts: dict[SourceRef, int] = defaultdict(int)
    for s in sources:
        counts[s] += 1
    return [{"domain": s.domain, "source_type": s.source_type, "items": n,
             **({"unverified": True} if s.unverified else {})} for s, n in counts.items()]  # fmt: skip
