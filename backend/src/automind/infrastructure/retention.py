"""Cache retention (spec 003 FR-026): expired search results and pages are removed; pages that support
validated values (referenced by evidence) are kept for provenance. Runs at start and every 24 h."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from sqlalchemy import delete, exists, select

from automind.infrastructure.db import Document, Evidence, PageRelevance, SearchCache, SiteReaderStat, sessionmaker
from automind.infrastructure.db.models import now

log = logging.getLogger(__name__)
EVERY = timedelta(hours=24)
STATS_DAYS = 180


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
        await s.commit()
    counts = {"search_cache": n_cache, "documents": n_docs, "page_relevance": n_rel, "site_reader_stats": n_stats}
    log.info("retention: %s", counts)
    return counts


async def retention_loop() -> None:
    while True:
        try:
            await run_retention()
        except Exception:  # noqa: BLE001 - retention must never stop the service
            log.exception("retention failed")
        await asyncio.sleep(EVERY.total_seconds())
