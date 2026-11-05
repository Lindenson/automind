"""Hard limits the system cannot change (spec 010 US7, constitution XII). Pure; checked on every change."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from .model import ACCESS_BLOCKING
from .seed_rules import denied


@dataclass(frozen=True)
class Guard:
    domain: str
    access: str
    frozen: bool
    current: str
    reverted_at: datetime | None = None  # last owner revert of this capability
    evidence_since_revert: bool = True  # a newer attempt or signal exists after that revert


def check(g: Guard, to: str, deny: Sequence[str], author: str = "system") -> str:
    """'apply', 'held' (frozen: journalled, not applied) or 'refused' (a hard limit)."""
    if author == "owner":
        return "apply"
    if (g.access in ACCESS_BLOCKING or denied(g.domain, deny)) and to != "blocked":
        return "refused"
    if g.current == "blocked":
        return "refused"  # only the owner lifts a block, by configuration
    if g.frozen:
        return "held"
    if g.reverted_at is not None and not g.evidence_since_revert:
        return "refused"  # a reverted change is not repeated without new evidence
    return "apply"
