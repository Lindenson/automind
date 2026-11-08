"""A page's evidence and what it gave (`documents`, `evidence`, `claims` and the area tables): one transaction per
page; the document is found by the SHA-256 of its text or stored. Implements `ports.EvidenceStore`; a database
failure becomes `PipelineStoreUnavailable`."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import asdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from automind.acquisition.pipeline.application.ports import PipelineStoreUnavailable
from automind.acquisition.pipeline.domain import rows as r
from automind.shared.infrastructure.db import models as m
from automind.shared.infrastructure.db.errors import translate_errors
from automind.shared.infrastructure.db.session import sessionmaker

_store_errors = translate_errors(PipelineStoreUnavailable)


class EvidenceRepo:
    """Evidence rows with their page's rows."""

    @_store_errors
    async def save(self, evidence: r.EvidenceIn, rows: Sequence[r.PageRow] = ()) -> str:
        """The evidence row and the page's rows in one transaction; returns the evidence id."""
        async with sessionmaker()() as s:
            e = m.Evidence(variant_id=evidence.variant_id, document_id=await _document_id(s, evidence),
                           favourite=evidence.favourite_priority is not None,
                           favourite_priority=evidence.favourite_priority, unverified=evidence.unverified,
                           url=evidence.url, source_name=evidence.source_name, domain=evidence.domain,
                           source_type=evidence.source_type, snippet_only=evidence.snippet_only)  # fmt: skip
            s.add(e)
            await s.flush()
            s.add_all([_orm(row, e.id) for row in rows])
            await s.commit()
            return e.id


async def _document_id(s: AsyncSession, evidence: r.EvidenceIn) -> str:
    if evidence.document_id is not None:
        return evidence.document_id
    sha = hashlib.sha256(evidence.text.encode()).hexdigest()
    doc = (await s.execute(select(m.Document).where(m.Document.content_sha256 == sha).limit(1))).scalar_one_or_none()
    if doc is None:
        doc = m.Document(url=evidence.url, title=evidence.title, text=evidence.text, content_sha256=sha)
        s.add(doc)
        await s.flush()
    return doc.id


def _orm(row: r.PageRow, evidence_id: str) -> m.Base:
    match row:
        case r.ClaimRow():
            return m.Claim(evidence_id=evidence_id, **asdict(row))
        case r.MaintenanceRow():
            return m.MaintenanceItem(evidence_ids=[evidence_id], **asdict(row))
        case r.ReviewRow():
            return m.ReviewItem(evidence_id=evidence_id, **asdict(row))
        case r.IssueRow():
            return m.Issue(evidence_id=evidence_id, **asdict(row))
        case r.ReliabilityRow():
            return m.ReliabilityStat(evidence_id=evidence_id, **asdict(row))
        case r.BrandFactRow():
            return m.ManufacturerFact(**asdict(row))
        case r.UsedPriceRow():
            return m.UsedPriceRange(evidence_id=evidence_id, **asdict(row))
        case r.RetentionRow():
            return m.ValueRetention(evidence_id=evidence_id, **asdict(row))
