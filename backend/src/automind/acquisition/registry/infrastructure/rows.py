"""Capability rows brought to now and read as records: the counts faded with the half-life, the score refreshed from
them (domain/score.py), and the record the rules read."""

from __future__ import annotations

from datetime import datetime

from automind.acquisition.registry.domain.config import ScoreConfig
from automind.acquisition.registry.domain.records import CapabilityView, ReviewedCapability
from automind.acquisition.registry.domain.score import Counts, decay, score_of
from automind.shared.infrastructure.db.models import CapabilityRow

DAY_SECONDS = 86400
DECAYED = ("attempts", "accepted", "right_w", "wrong_w", "robots_refusals", "junk", "cost_eur", "signals_w",
           "families_agree")  # fmt: skip


def fade(cap: CapabilityRow, half_life_days: float, now: datetime) -> None:
    """Fade counts and signals to `now`, so a site that went bad loses trust (spec 010 US6)."""
    days = (now - cap.decayed_at).total_seconds() / DAY_SECONDS if cap.decayed_at else 0.0
    if days > 0:
        for f in DECAYED:
            setattr(cap, f, decay(float(getattr(cap, f) or 0.0), days, half_life_days))
    cap.decayed_at = now


def rescore(cap: CapabilityRow, source_type: str, cfg: ScoreConfig) -> None:
    """Refresh the stored score and its parts from the counts."""
    q = score_of(Counts(cap.attempts, cap.accepted, cap.right_w, cap.wrong_w, cap.cost_eur), source_type, cfg)
    cap.score, cap.acc_mean, cap.acc_lb, cap.yield_ = q.score, q.acc_mean, q.acc_lb, q.yield_


def view(r: CapabilityRow, source_type: str | None, access: str | None) -> CapabilityView:
    """The record of a capability with its source's type and access ("OTHER" / "unknown" when missing)."""
    return CapabilityView(
        domain=r.domain, area=r.area, market=r.market, status=r.status, score=float(r.score or 0.0),
        priority_seed=r.priority_seed, attempts=float(r.attempts or 0.0), accepted=float(r.accepted or 0.0),
        right_w=float(r.right_w or 0.0), wrong_w=float(r.wrong_w or 0.0), cost_eur=float(r.cost_eur or 0.0),
        url_patterns=tuple(str(p) for p in r.url_patterns or []), source_type=source_type or "OTHER",
        access=access or "unknown", id=r.id,
    )  # fmt: skip


def reviewed(r: CapabilityRow, score_before: float) -> ReviewedCapability:
    """The record of a faded and rescored capability for the review."""
    return ReviewedCapability(
        id=r.id, domain=r.domain, area=r.area, market=r.market, status=r.status, status_since=r.status_since,
        attempts=float(r.attempts), acc_lb=float(r.acc_lb), yield_=float(r.yield_), score=float(r.score),
        score_before=score_before, signals_w=float(r.signals_w or 0.0), recent=tuple(r.recent or []),
        last_used=r.last_used,
    )  # fmt: skip
