"""The chat's retention steps: policy passes (spec 015 §H D2) and turn understandings (spec 013 T033) older than 90
days are deleted. The API runs them after the engine's cache retention, at start and every 24 h
(`retention_loop(prune_decisions, prune_understanding)`, heartbeat "retention")."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from automind.chat.infrastructure.persistence import understanding
from automind.chat.infrastructure.persistence.decisions import KEEP_DAYS, DecisionRepo
from automind.chat.infrastructure.persistence.understanding import UnderstandingRepo

log = logging.getLogger(__name__)


async def prune_decisions(repo: DecisionRepo | None = None, now: datetime | None = None) -> int:
    """Delete the policy passes older than `KEEP_DAYS`; returns how many. Raises `StoreUnavailable`."""
    cut = (now or datetime.now(UTC)) - timedelta(days=KEEP_DAYS)
    deleted = await (repo or DecisionRepo()).prune(cut)
    log.info("retention.policy_decisions deleted=%s before=%s", deleted, cut.isoformat())
    return deleted


async def prune_understanding(repo: UnderstandingRepo | None = None, now: datetime | None = None) -> int:
    """Delete the turn understandings older than `understanding.KEEP_DAYS`; returns how many. Raises
    `StoreUnavailable`."""
    cut = (now or datetime.now(UTC)) - timedelta(days=understanding.KEEP_DAYS)
    deleted = await (repo or UnderstandingRepo()).prune(cut)
    log.info("retention.turn_understanding deleted=%s before=%s", deleted, cut.isoformat())
    return deleted
