"""What the registry's rules read of a stored capability: plain records, so no database row reaches a rule. Pure."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from automind.shared.contracts.json import JsonObject


@dataclass(frozen=True)
class CapabilityView:
    """A capability (a source for a kind of data on a market) with its source's type and access.

    `source_type` and `access` are "OTHER" / "unknown" when the source row is missing."""

    domain: str
    area: str
    market: str
    status: str
    score: float = 0.0
    priority_seed: int | None = None
    attempts: float = 0.0
    accepted: float = 0.0
    right_w: float = 0.0
    wrong_w: float = 0.0
    cost_eur: float = 0.0
    url_patterns: tuple[str, ...] = ()
    source_type: str = "OTHER"
    access: str = "unknown"
    id: str = ""


@dataclass(frozen=True)
class ReviewedCapability:
    """A capability as the daily review sees it: its counts faded and its score refreshed to now.

    `score_before` is the score before that refresh (the ranks before the review are taken from it)."""

    id: str
    domain: str
    area: str
    market: str
    status: str
    status_since: datetime
    attempts: float
    acc_lb: float
    yield_: float
    score: float
    score_before: float
    signals_w: float = 0.0
    recent: tuple[bool, ...] = ()
    last_used: datetime | None = None


@dataclass(frozen=True)
class SourceState:
    """A source's access verdict and whether the owner froze it."""

    access: str = "unknown"
    frozen: bool = False


@dataclass(frozen=True)
class JournalEntry:
    """One `registry_changes` row written by the system (author "system")."""

    domain: str
    change: str
    reason: str
    capability_id: str | None = None
    before: JsonObject = field(default_factory=dict)
    after: JsonObject = field(default_factory=dict)
    evidence: JsonObject = field(default_factory=dict)
    held: bool = False


@dataclass(frozen=True)
class StatusMove:
    """A capability's new status, applied by the review."""

    capability_id: str
    to: str
