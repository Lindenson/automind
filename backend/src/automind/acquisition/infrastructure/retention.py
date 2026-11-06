"""Cache retention (spec 003 FR-026): expired search results and pages are removed; pages that support
validated values (referenced by evidence) are kept for provenance. Runs at start and every 24 h."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from sqlalchemy import delete, exists, select, text

from automind.shared.infrastructure.db import (
    Document,
    Evidence,
    PageRelevance,
    SearchCache,
    SiteReaderStat,
    sessionmaker,
)
from automind.shared.infrastructure.db.models import RegistryAttempt, now
from automind.shared.infrastructure.metrics import heartbeat

log = logging.getLogger(__name__)
EVERY = timedelta(hours=24)
STATS_DAYS = 180
ATTEMPT_DAYS = 180  # spec 010: registry_attempts are kept 180 days
# LangGraph writes a checkpoint per super-step on one thread per chat; only the newest are needed to resume
# a turn (reviewer 2026-11-03: the tables grew without bound). Older ones, their writes and unreferenced
# blobs are removed.
KEEP_CHECKPOINTS = 40

_PRUNE_CHECKPOINTS = text(
    """
    WITH ranked AS (
        SELECT thread_id, checkpoint_ns, checkpoint_id,
               row_number() OVER (PARTITION BY thread_id, checkpoint_ns ORDER BY checkpoint_id DESC) AS rn
        FROM checkpoints)
    DELETE FROM checkpoints c USING ranked r
    WHERE c.thread_id = r.thread_id AND c.checkpoint_ns = r.checkpoint_ns AND c.checkpoint_id = r.checkpoint_id
      AND r.rn > :keep
    """
)
_PRUNE_WRITES = text(
    """
    DELETE FROM checkpoint_writes w WHERE NOT EXISTS (
        SELECT 1 FROM checkpoints c WHERE c.thread_id = w.thread_id AND c.checkpoint_ns = w.checkpoint_ns
          AND c.checkpoint_id = w.checkpoint_id)
    """
)
_PRUNE_BLOBS = text(
    """
    DELETE FROM checkpoint_blobs b WHERE NOT EXISTS (
        SELECT 1 FROM checkpoints c WHERE c.thread_id = b.thread_id AND c.checkpoint_ns = b.checkpoint_ns
          AND c.checkpoint -> 'channel_versions' ->> b.channel = b.version)
    """
)


async def prune_checkpoints(keep: int = KEEP_CHECKPOINTS) -> dict[str, int]:
    async with sessionmaker()() as s:
        exists_ = (await s.execute(text("SELECT to_regclass('checkpoints') IS NOT NULL"))).scalar()
        if not exists_:
            return {}
        n_cp = (await s.execute(_PRUNE_CHECKPOINTS, {"keep": keep})).rowcount or 0
        n_w = (await s.execute(_PRUNE_WRITES)).rowcount or 0
        n_b = (await s.execute(_PRUNE_BLOBS)).rowcount or 0
        await s.commit()
    return {"checkpoints": n_cp, "checkpoint_writes": n_w, "checkpoint_blobs": n_b}


async def run_retention() -> dict[str, int]:
    t = now()
    async with sessionmaker()() as s:
        n_cache = (await s.execute(delete(SearchCache).where(SearchCache.expires_at < t))).rowcount or 0
        referenced = exists(select(Evidence.id).where(Evidence.document_id == Document.id))
        expired = select(Document.id).where(Document.expires_at < t, ~referenced)
        n_rel = (await s.execute(delete(PageRelevance).where(PageRelevance.document_id.in_(expired)))).rowcount or 0
        n_docs = (await s.execute(delete(Document).where(Document.id.in_(expired)))).rowcount or 0
        old = (t - timedelta(days=STATS_DAYS)).date()
        n_stats = (await s.execute(delete(SiteReaderStat).where(SiteReaderStat.day < old))).rowcount or 0
        cut = t - timedelta(days=ATTEMPT_DAYS)
        n_att = (await s.execute(delete(RegistryAttempt).where(RegistryAttempt.created_at < cut))).rowcount or 0
        await s.commit()
    counts = {"search_cache": n_cache, "documents": n_docs, "page_relevance": n_rel, "site_reader_stats": n_stats,
              "registry_attempts": n_att}  # fmt: skip
    counts |= await prune_checkpoints()
    # spec 011: raw page snapshots are pruned by the worker's `retention_snapshots` task
    log.info("retention: %s", counts)
    return counts


async def retention_loop() -> None:
    heartbeat.register("retention", EVERY.total_seconds())
    while True:
        try:
            await run_retention()
            heartbeat.beat("retention", True)
        except Exception:  # noqa: BLE001 - retention must never stop the service
            log.exception("retention failed")
            heartbeat.beat("retention", False)
        await asyncio.sleep(EVERY.total_seconds())
