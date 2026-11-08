"""Hard limits the system cannot change (spec 010 US7, constitution XII). Pure; checked on every change."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from automind.acquisition.registry.domain.model import ACCESS_BLOCKING, CapabilityStatus
from automind.acquisition.registry.domain.seed_rules import denied


@dataclass(frozen=True)
class Guard:
    """What the hard limits read of a capability and its source."""

    domain: str
    access: str
    frozen: bool
    current: str
    reverted_at: datetime | None = None  # last owner revert of this capability
    evidence_since_revert: bool = True  # a newer attempt or signal exists after that revert


class GuardVerdict(StrEnum):
    """What the hard limits say of a proposed status move."""

    APPLY = "apply"
    HELD = "held"  # a frozen source: journalled, not applied
    REFUSED = "refused"  # a hard limit


def check(g: Guard, to: str, deny: Sequence[str], author: str = "system") -> GuardVerdict:
    """Whether the move of `g` to `to` may be applied (the owner's always may)."""
    if author == "owner":
        return GuardVerdict.APPLY
    if (g.access in ACCESS_BLOCKING or denied(g.domain, deny)) and to != CapabilityStatus.BLOCKED:
        return GuardVerdict.REFUSED
    if g.current == CapabilityStatus.BLOCKED:
        return GuardVerdict.REFUSED  # only the owner lifts a block, by configuration
    if g.frozen:
        return GuardVerdict.HELD
    if g.reverted_at is not None and not g.evidence_since_revert:
        return GuardVerdict.REFUSED  # a reverted change is not repeated without new evidence
    return GuardVerdict.APPLY
