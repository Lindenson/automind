"""Snapshot compression and retention rules (spec 011 research R1). Pure.

Raw page bodies are content-addressed by the sha256 of the raw bytes and compressed with zstd. Retention classes:
`plain` (kept 30 days), `accepted` (the page gave accepted values: 180 days), `pinned` (in a running experiment's
corpus: kept until it ends). Over the size cap the oldest replay-only pages go first; pinned pages never.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import zstandard

CODEC = "zstd"
PLAIN, ACCEPTED, PINNED = "plain", "accepted", "pinned"
GB = 1024**3


@dataclass(frozen=True)
class RetentionCfg:
    plain_days: int
    accepted_days: int
    max_bytes: int
    level: int

    @classmethod
    def from_config(cls, snapshots: dict[str, Any]) -> RetentionCfg:
        """From `config/acquisition.yaml: snapshots` (the only source of these values; a missing key fails)."""
        keep = snapshots["keep_days"]
        return cls(
            plain_days=int(keep["plain"]),
            accepted_days=int(keep["accepted"]),
            max_bytes=int(float(snapshots["max_gb"]) * GB),
            level=int(snapshots["zstd_level"]),
        )


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def compress(raw: bytes, level: int) -> bytes:
    return zstandard.ZstdCompressor(level=level).compress(raw)


def decompress(body: bytes) -> bytes:
    return zstandard.ZstdDecompressor().decompress(body)


def retention_class(accepted_values: int, pinned: bool) -> str:
    if pinned:
        return PINNED
    return ACCEPTED if accepted_values > 0 else PLAIN


def keep_until(fetched_at: datetime, cls: str, cfg: RetentionCfg) -> datetime | None:
    if cls == PINNED:
        return None
    return fetched_at + timedelta(days=cfg.accepted_days if cls == ACCEPTED else cfg.plain_days)


@dataclass(frozen=True)
class SnapshotRow:
    id: str
    fetched_at: datetime
    retention_class: str
    keep_until: datetime | None
    stored_bytes: int  # of its blob (0 when it has none)
    blob_sha256: str | None


def eviction_plan(
    rows: list[SnapshotRow], cap_bytes: int, now: datetime | None = None, accepted_days: int = 180
) -> list[str]:
    """Snapshot ids to delete, in order: every expired row, then (while the stored bytes exceed the cap) the oldest
    `plain` rows, then the oldest `accepted` rows older than `accepted_days`; never `pinned` ones. A blob shared by
    several snapshots frees its bytes only when its last snapshot goes."""
    now = now or datetime.now(UTC)
    refs: dict[str, int] = {}
    size: dict[str, int] = {}
    for r in rows:
        if r.blob_sha256:
            refs[r.blob_sha256] = refs.get(r.blob_sha256, 0) + 1
            size[r.blob_sha256] = r.stored_bytes
    total = sum(size.values())
    plan: list[str] = []
    gone: set[str] = set()

    def drop(r: SnapshotRow) -> None:
        nonlocal total
        plan.append(r.id)
        gone.add(r.id)
        if r.blob_sha256:
            refs[r.blob_sha256] -= 1
            if refs[r.blob_sha256] == 0:
                total -= size[r.blob_sha256]

    live = [r for r in rows if r.retention_class != PINNED]
    for r in sorted(live, key=lambda r: r.fetched_at):
        if r.keep_until is not None and r.keep_until <= now:
            drop(r)
    old_accepted = now - timedelta(days=accepted_days)
    order = sorted((r for r in live if r.id not in gone and r.retention_class == PLAIN), key=lambda r: r.fetched_at)
    order += sorted(
        (r for r in live if r.id not in gone and r.retention_class == ACCEPTED and r.fetched_at <= old_accepted),
        key=lambda r: r.fetched_at,
    )
    for r in order:
        if total <= cap_bytes:
            break
        drop(r)
    return plan
