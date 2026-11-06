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

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from automind.acquisition.registry.domain.model import ACCESS_BLOCKING


@dataclass(frozen=True)
class CapState:
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
    to: str
    reason: str


def _f(x: float) -> str:
    return f"{x:.2f}"


def _candidate(c: CapState, lc: Mapping[str, Any], days: float) -> Move | None:
    pro = lc.get("promote") or {}
    if (
        c.attempts >= float(pro.get("min_attempts", 8))
        and c.acc_lb >= float(pro.get("min_acc_lb", 0.6))
        and c.yield_ >= float(pro.get("min_yield", 0.2))
        and c.signals_w >= float(pro.get("min_signals", 5))
    ):
        return Move(
            "active",
            f"accuracy lower bound {_f(c.acc_lb)} and yield {_f(c.yield_)} over {c.attempts:.0f} attempts, "
            f"{c.signals_w:.1f} accuracy signals",
        )
    return None


def _zero(c: CapState, lc: Mapping[str, Any]) -> tuple[bool, int]:
    n = int((lc.get("degrade") or {}).get("zero_in_last", 10))
    return len(c.recent) >= n and not any(c.recent[-n:]), n


def _active(c: CapState, lc: Mapping[str, Any], days: float) -> Move | None:
    deg = lc.get("degrade") or {}
    zero, n = _zero(c, lc)
    if zero:
        return Move("degraded", f"no accepted value in the last {n} attempts")
    low = c.acc_lb < float(deg.get("max_acc_lb", 0.45)) or c.yield_ < float(deg.get("max_yield", 0.05))
    if c.attempts >= float(deg.get("min_attempts", 10)) and low:
        return Move("degraded", f"accuracy lower bound {_f(c.acc_lb)} or yield {_f(c.yield_)} below the floor")
    return None


def _degraded(c: CapState, lc: Mapping[str, Any], days: float) -> Move | None:
    rec = lc.get("recover") or {}
    zero, _ = _zero(c, lc)
    if not zero and c.acc_lb >= float(rec.get("min_acc_lb", 0.55)) and c.yield_ >= float(rec.get("min_yield", 0.15)):
        return Move("active", f"recovered: accuracy lower bound {_f(c.acc_lb)}, yield {_f(c.yield_)}")
    if days >= float(lc.get("retire_after_days", 21)):
        return Move("retired", f"degraded for {days:.0f} days without recovery")
    return None


def _retired(c: CapState, lc: Mapping[str, Any], days: float) -> Move | None:
    if days >= float(lc.get("retired_retry_days", 30)):
        return Move("candidate", f"retired {days:.0f} days ago: one more try")
    return None


def _discovered(c: CapState, lc: Mapping[str, Any], days: float) -> Move | None:
    return Move("candidate", "admitted: robots and terms allow automated reading") if c.access == "ok" else None


_RULES = {
    "discovered": _discovered,
    "candidate": _candidate,
    "active": _active,
    "degraded": _degraded,
    "retired": _retired,
}


def transition(c: CapState, cfg: Mapping[str, Any], now: datetime) -> Move | None:
    if c.status == "blocked":
        return None
    if c.access in ACCESS_BLOCKING:
        return Move("blocked", f"access check: {c.access.replace('_', ' ')}")
    rule = _RULES.get(c.status)
    days = (now - c.status_since).total_seconds() / 86400
    return rule(c, cfg.get("lifecycle") or {}, days) if rule else None
