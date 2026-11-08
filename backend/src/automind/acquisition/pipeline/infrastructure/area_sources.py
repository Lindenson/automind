"""The sources of an area's accepted values, by where the area stores them: spec claims, claims plus the service
schedule's evidence, the make's facts, or the area's own item table (with reliability statistics)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from automind.acquisition.pipeline.domain.hits import SourceKind, SourceRef
from automind.shared import evidence as ev
from automind.shared.infrastructure.db import models as m

_TABLES: dict[str, Any] = {"reviews": m.ReviewItem, "reliability": m.Issue, "used_issues": m.Issue,
                           "used_price": m.UsedPriceRange, "depreciation": m.ValueRetention}  # fmt: skip
_SOURCE = (m.Evidence.domain, m.Evidence.source_type, m.Evidence.unverified)


async def of(s: AsyncSession, variant_id: str, make: str, area: str, kind: SourceKind) -> list[SourceRef]:
    """The sources in the order the queries return them (KeyError: an area with no store of its own)."""
    if kind == "claims":
        return await _claims(s, variant_id, area)
    if kind == "maintenance":
        return await _claims(s, variant_id, area) + await _schedule(s, variant_id)
    if kind == "manufacturer":
        urls = (await s.execute(select(m.ManufacturerFact.url).where(m.ManufacturerFact.make == make))).scalars()
        return [SourceRef(ev.domain_of(u), ev.classify_source(u), False) for u in urls]
    return await _items(s, variant_id, area)


async def _claims(s: AsyncSession, variant_id: str, area: str) -> list[SourceRef]:
    q = select(*_SOURCE).join(m.Claim, m.Claim.evidence_id == m.Evidence.id)
    return await _refs(s, q.where(m.Claim.variant_id == variant_id, m.Claim.area == area,
                                  m.Claim.status == "ACCEPTED"))  # fmt: skip


async def _schedule(s: AsyncSession, variant_id: str) -> list[SourceRef]:
    out: list[SourceRef] = []
    rows = await s.execute(select(m.MaintenanceItem.evidence_ids).where(m.MaintenanceItem.variant_id == variant_id))
    for (ids,) in rows.all():
        for eid in ids or []:
            e = await s.get(m.Evidence, eid)
            if e:
                out.append(SourceRef(e.domain, e.source_type, bool(e.unverified)))
    return out


async def _items(s: AsyncSession, variant_id: str, area: str) -> list[SourceRef]:
    table = _TABLES[area]
    q = select(*_SOURCE).join(table, table.evidence_id == m.Evidence.id).where(table.variant_id == variant_id)
    if table is m.UsedPriceRange:
        q = q.where(m.UsedPriceRange.status == "ACCEPTED")
    if table is m.Issue:
        q = q.where(m.Issue.area == area)
    out = await _refs(s, q)
    if area == "reliability":
        q2 = select(*_SOURCE).join(m.ReliabilityStat, m.ReliabilityStat.evidence_id == m.Evidence.id)
        out += await _refs(s, q2.where(m.ReliabilityStat.variant_id == variant_id))
    return out


async def _refs(s: AsyncSession, q: Select[str, str, bool]) -> list[SourceRef]:
    return [SourceRef(str(d), str(t), bool(u)) for d, t, u in (await s.execute(q)).all()]
