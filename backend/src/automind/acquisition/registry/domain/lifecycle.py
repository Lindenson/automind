"""Lifecycle of a capability (spec 010 US7, research R9). Pure.

discovered → candidate (admitted) | blocked
candidate  → active    when the sample is big enough, the accuracy lower bound and yield pass, and there are at least
                       `promote.min_signals` accuracy signals (spec 011 FR-012: never on yield alone)
active     → degraded  when the lower bound or the yield falls, or the last N attempts all failed
degraded   → active    when it recovers;  degraded → retired after N days without recovery
retired    → candidate after the retry period (one more chance)
blocked    never changes here (hard limit, see limits.py)
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from automind.acquisition.registry.domain.config import Lifecycle
from automind.acquisition.registry.domain.model import ACCESS_BLOCKING, CapabilityStatus

DAY_SECONDS = 86400


@dataclass(frozen=True)
class CapState:
    """What the lifecycle reads of a capability: its status and since when, counts, access and recent outcomes."""

    status: str
    attempts: float
    acc_lb: float
    yield_: float
    status_since: datetime
    access: str = "unknown"
    recent: Sequence[bool] = field(default_factory=tuple)
    signals_w: float = 0.0  # spec 011: decayed weight of accuracy signals (priors excluded)


@dataclass(frozen=True)
class Move:
    """A proposed status and why."""

    to: str
    reason: str


def transition(c: CapState, lc: Lifecycle, now: datetime) -> Move | None:
    """The move the lifecycle proposes for a capability now, None when it stays. A blocked capability never moves
    here; an access-blocked source's capability moves to blocked whatever its status."""
    if c.status == CapabilityStatus.BLOCKED:
        return None
    if c.access in ACCESS_BLOCKING:
        return Move(CapabilityStatus.BLOCKED, f"access check: {c.access.replace('_', ' ')}")
    rule = _RULES.get(c.status)
    days = (now - c.status_since).total_seconds() / DAY_SECONDS
    return rule(c, lc, days) if rule else None


def _f(x: float) -> str:
    return f"{x:.2f}"


def _candidate(c: CapState, lc: Lifecycle, days: float) -> Move | None:
    pro = lc.promote
    if (
        c.attempts >= pro.min_attempts
        and c.acc_lb >= pro.min_acc_lb
        and c.yield_ >= pro.min_yield
        and c.signals_w >= pro.min_signals
    ):
        return Move(
            CapabilityStatus.ACTIVE,
            f"accuracy lower bound {_f(c.acc_lb)} and yield {_f(c.yield_)} over {c.attempts:.0f} attempts, "
            f"{c.signals_w:.1f} accuracy signals",
        )
    return None


def _zero(c: CapState, lc: Lifecycle) -> tuple[bool, int]:
    n = lc.degrade.zero_in_last
    return len(c.recent) >= n and not any(c.recent[-n:]), n


def _active(c: CapState, lc: Lifecycle, days: float) -> Move | None:
    deg = lc.degrade
    zero, n = _zero(c, lc)
    if zero:
        return Move(CapabilityStatus.DEGRADED, f"no accepted value in the last {n} attempts")
    low = c.acc_lb < deg.max_acc_lb or c.yield_ < deg.max_yield
    if c.attempts >= deg.min_attempts and low:
        return Move(
            CapabilityStatus.DEGRADED, f"accuracy lower bound {_f(c.acc_lb)} or yield {_f(c.yield_)} below the floor"
        )
    return None


def _degraded(c: CapState, lc: Lifecycle, days: float) -> Move | None:
    rec = lc.recover
    zero, _ = _zero(c, lc)
    if not zero and c.acc_lb >= rec.min_acc_lb and c.yield_ >= rec.min_yield:
        return Move(CapabilityStatus.ACTIVE, f"recovered: accuracy lower bound {_f(c.acc_lb)}, yield {_f(c.yield_)}")
    if days >= lc.retire_after_days:
        return Move(CapabilityStatus.RETIRED, f"degraded for {days:.0f} days without recovery")
    return None


def _retired(c: CapState, lc: Lifecycle, days: float) -> Move | None:
    if days >= lc.retired_retry_days:
        return Move(CapabilityStatus.CANDIDATE, f"retired {days:.0f} days ago: one more try")
    return None


def _discovered(c: CapState, lc: Lifecycle, days: float) -> Move | None:
    return (
        Move(CapabilityStatus.CANDIDATE, "admitted: robots and terms allow automated reading")
        if c.access == "ok"
        else None
    )


_RULES: dict[str, Callable[[CapState, Lifecycle, float], Move | None]] = {
    CapabilityStatus.DISCOVERED: _discovered,
    CapabilityStatus.CANDIDATE: _candidate,
    CapabilityStatus.ACTIVE: _active,
    CapabilityStatus.DEGRADED: _degraded,
    CapabilityStatus.RETIRED: _retired,
}
