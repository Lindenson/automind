"""Snapshot store (spec 011 FR-001, research R1): every network fetch keeps its raw body for replay.

`write()` is called by the page store on every network fetch (never on a cache hit); compression runs off the event
loop. A body already stored (same sha256) is not stored again. `mark()` records accepted values and variants a page
was used for, which upgrades its retention class. `load()` and `iter_replayable()` serve replay.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import or_, select, tuple_
from sqlalchemy.dialects.postgresql import insert

from automind.acquisition.infrastructure import config as acq_config
from automind.acquisition.snapshots import codec
from automind.shared.evidence import domain_of
from automind.shared.infrastructure.db import PageSnapshot, SnapshotBlob, sessionmaker, uid
from automind.shared.infrastructure.metrics import prom

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SnapshotRef:
    id: str
    url: str
    final_url: str | None
    domain: str
    fetched_at: datetime
    content_type: str | None
    variant_ids: tuple[str, ...]
    blob_sha256: str


async def write(
    url: str,
    final_url: str | None,
    raw: bytes | None,
    content_type: str | None,
    http_status: int | None,
    status: str,
    document_id: str | None,
) -> str:
    """Store one fetch event (and its compressed body when there is one); returns the snapshot id."""
    from automind.acquisition.infrastructure.pages import url_hash  # noqa: PLC0415 - the page store imports this module

    cfg = acq_config.snapshot_retention()
    now = datetime.now(UTC)
    sha: str | None = None
    if raw is not None:
        sha = codec.sha256(raw)
        body = await asyncio.to_thread(codec.compress, raw, cfg.level)
        prom.inc("snapshot_bytes", len(raw), kind="raw")
        prom.inc("snapshot_bytes", len(body), kind="stored")
    sid = uid()
    async with sessionmaker()() as s:
        if raw is not None and sha is not None:
            await s.execute(
                insert(SnapshotBlob)
                .values(
                    sha256=sha, codec=codec.CODEC, body=body, raw_bytes=len(raw), stored_bytes=len(body), created_at=now
                )  # fmt: skip
                .on_conflict_do_nothing(index_elements=["sha256"])
            )
        s.add(
            PageSnapshot(
                id=sid, url=url, url_hash=url_hash(url), final_url=final_url, domain=domain_of(final_url or url),
                document_id=document_id, fetched_at=now, blob_sha256=sha, content_type=content_type,
                http_status=http_status, status=status, replayable=status == "OK" and raw is not None,
                retention_class=codec.PLAIN, keep_until=codec.keep_until(now, codec.PLAIN, cfg),
            )
        )  # fmt: skip
        await s.commit()
    prom.inc("snapshots", status=status)
    return sid


async def mark(snapshot_id: str, accepted_values: int, variant_id: str | None) -> None:
    """Add accepted values and the variant the page was used for; a page with accepted values is kept longer."""
    cfg = acq_config.snapshot_retention()
    async with sessionmaker()() as s:
        row = (
            await s.execute(select(PageSnapshot).where(PageSnapshot.id == snapshot_id).with_for_update())
        ).scalar_one_or_none()
        if row is None:
            return
        row.accepted_values = (row.accepted_values or 0) + max(0, int(accepted_values))
        if variant_id and variant_id not in (row.variant_ids or []):
            row.variant_ids = [*(row.variant_ids or []), variant_id]
        if row.retention_class != codec.PINNED:
            cls = codec.retention_class(row.accepted_values, pinned=False)
            row.retention_class, row.keep_until = cls, codec.keep_until(row.fetched_at, cls, cfg)
        await s.commit()


async def load(snapshot_id: str) -> tuple[bytes, str]:
    """(raw body, final URL) of a replayable snapshot; KeyError when it has no body."""
    async with sessionmaker()() as s:
        row = (
            await s.execute(
                select(SnapshotBlob.body, PageSnapshot.final_url, PageSnapshot.url)
                .join(SnapshotBlob, SnapshotBlob.sha256 == PageSnapshot.blob_sha256)
                .where(PageSnapshot.id == snapshot_id)
            )
        ).first()
    if row is None:
        raise KeyError(snapshot_id)
    body, final_url, url = row
    return await asyncio.to_thread(codec.decompress, bytes(body)), final_url or url


async def load_bodies(shas: list[str]) -> dict[str, bytes]:
    """Raw bodies of several blobs at once (replay reads in batches)."""
    if not shas:
        return {}
    async with sessionmaker()() as s:
        rows = (
            await s.execute(select(SnapshotBlob.sha256, SnapshotBlob.body).where(SnapshotBlob.sha256.in_(shas)))
        ).all()

    def unpack() -> dict[str, bytes]:
        return {sha: codec.decompress(bytes(body)) for sha, body in rows}

    return await asyncio.to_thread(unpack)


async def latest_for_document(document_id: str) -> str | None:
    """The newest snapshot of a cached page (a cache hit reuses the snapshot of its last fetch)."""
    async with sessionmaker()() as s:
        return (
            await s.execute(
                select(PageSnapshot.id)
                .where(PageSnapshot.document_id == document_id)
                .order_by(PageSnapshot.fetched_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()


def _domain_matches(domain: str, domains: list[str]) -> bool:
    return any(domain == d or domain.endswith("." + d) for d in domains)


async def iter_replayable(
    domains: list[str] | None, since: datetime | None, until: datetime | None, batch: int = 500
) -> AsyncIterator[list[SnapshotRef]]:
    """Replayable snapshots of these domains (all when None) fetched in [since, until], oldest first, in batches."""
    last: tuple[datetime, str] | None = None
    while True:
        q = select(PageSnapshot).where(PageSnapshot.replayable, PageSnapshot.blob_sha256.is_not(None))
        if since is not None:
            q = q.where(PageSnapshot.fetched_at >= since)
        if until is not None:
            q = q.where(PageSnapshot.fetched_at <= until)
        if domains:
            q = q.where(or_(*(PageSnapshot.domain == d for d in domains),
                            *(PageSnapshot.domain.like(f"%.{d}") for d in domains)))  # fmt: skip
        if last is not None:
            q = q.where(tuple_(PageSnapshot.fetched_at, PageSnapshot.id) > tuple_(*last))
        q = q.order_by(PageSnapshot.fetched_at, PageSnapshot.id).limit(batch)
        async with sessionmaker()() as s:
            rows = list((await s.execute(q)).scalars())
        if not rows:
            return
        yield [
            SnapshotRef(
                r.id,
                r.url,
                r.final_url,
                r.domain,
                r.fetched_at,
                r.content_type,
                tuple(r.variant_ids or ()),
                str(r.blob_sha256),
            )  # fmt: skip
            for r in rows
            if not domains or _domain_matches(r.domain, domains)
        ]
        last = (rows[-1].fetched_at, rows[-1].id)
        if len(rows) < batch:
            return
