"""Registry entities (spec 010 data-model.md). Pure."""

from __future__ import annotations

from dataclasses import dataclass, field

from automind.shared.contracts.json import JsonObject

STATUSES = ("discovered", "candidate", "active", "degraded", "retired", "blocked")
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
