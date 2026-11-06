"""Snapshot retention (spec 011 FR-001, research R1): expired snapshots go, then the size cap is enforced (oldest
replay-only pages first, never pinned ones), then blobs no snapshot refers to. Runs with the cache retention until
the worker takes it over (T055)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import delete, select, text

from automind.acquisition.infrastructure import config as acq_config
from automind.acquisition.snapshots import codec
from automind.acquisition.snapshots.codec import RetentionCfg, SnapshotRow
from automind.shared.infrastructure.db import PageSnapshot, SnapshotBlob, sessionmaker

log = logging.getLogger(__name__)
CHUNK = 1000

_ORPHAN_BLOBS = text(
    "DELETE FROM snapshot_blobs b WHERE NOT EXISTS (SELECT 1 FROM page_snapshots p WHERE p.blob_sha256 = b.sha256)"
)


async def _rows() -> list[SnapshotRow]:
    async with sessionmaker()() as s:
        res = await s.execute(
            select(
                PageSnapshot.id, PageSnapshot.fetched_at, PageSnapshot.retention_class, PageSnapshot.keep_until,
                SnapshotBlob.stored_bytes, PageSnapshot.blob_sha256,
            ).join(SnapshotBlob, SnapshotBlob.sha256 == PageSnapshot.blob_sha256, isouter=True)
        )  # fmt: skip
        return [SnapshotRow(i, f, c, k, int(b or 0), sha) for i, f, c, k, b, sha in res.all()]


async def run_snapshot_retention(cfg: RetentionCfg | None = None, now: datetime | None = None) -> dict[str, int]:
    cfg = cfg or acq_config.snapshot_retention()
    plan = codec.eviction_plan(await _rows(), cfg.max_bytes, now or datetime.now(UTC), cfg.accepted_days)
    n_blobs = 0
    async with sessionmaker()() as s:
        for i in range(0, len(plan), CHUNK):
            await s.execute(delete(PageSnapshot).where(PageSnapshot.id.in_(plan[i : i + CHUNK])))
        n_blobs = (await s.execute(_ORPHAN_BLOBS)).rowcount or 0  # type: ignore[attr-defined]
        await s.commit()
    counts = {"page_snapshots": len(plan), "snapshot_blobs": n_blobs}
    log.info("snapshot retention: %s", counts)
    return counts
