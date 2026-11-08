"""Registry entities (spec 010 data-model.md). Pure."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from automind.shared.contracts.json import JsonObject


class CapabilityStatus(StrEnum):
    """Where a source's capability (domain × area × market) is in its life (`registry_capabilities.status`)."""

    DISCOVERED = "discovered"  # met in an open search; admission not checked yet
    CANDIDATE = "candidate"  # admitted: explored within a small budget
    ACTIVE = "active"  # proven: planned first
    DEGRADED = "degraded"  # was active, now failing
    RETIRED = "retired"  # degraded too long (retried later as a candidate)
    BLOCKED = "blocked"  # robots, terms, classifieds or the deny-list: never read


STATUSES = tuple(CapabilityStatus)
ACCESS_BLOCKING = ("classifieds", "terms_forbid", "robots_blocked")


@dataclass
class Source:
    """A site: its type, mirror family, markets and languages, and the access verdict with its evidence."""

    domain: str
    source_type: str
    family: str
    markets: list[str] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)
    access: str = "unknown"
    access_evidence: JsonObject = field(default_factory=dict)
    checked_at: str | None = None
    reader: str | None = None
    frozen: bool = False


@dataclass
class Capability:
    """A source for one kind of data (area) on one market, with its status and counts."""

    domain: str
    area: str
    market: str
    status: str
    priority_seed: int | None = None
    attempts: float = 0.0
    accepted: float = 0.0
    right_w: float = 0.0
    wrong_w: float = 0.0
