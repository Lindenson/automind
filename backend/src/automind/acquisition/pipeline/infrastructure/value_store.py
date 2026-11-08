"""A variant's selected values (`spec_values`) over its accepted claims and its service schedule, and the
variant's gearbox. Implements `ports.ValueStore`; a database failure becomes `PipelineStoreUnavailable`."""

from __future__ import annotations

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from automind.acquisition.pipeline.application.ports import PipelineStoreUnavailable, SelectValues
from automind.acquisition.pipeline.domain.selection import ScheduleItem
from automind.shared import evidence as ev
from automind.shared.infrastructure.db import models as m
from automind.shared.infrastructure.db.errors import translate_errors
from automind.shared.infrastructure.db.session import sessionmaker

_store_errors = translate_errors(PipelineStoreUnavailable)
_LOCK = text("SELECT pg_advisory_xact_lock(hashtext(:k))")


class ValueRepo:
    """Selected values, accepted claims and the gearbox column."""

    @_store_errors
    async def known_values(self, variant_id: str) -> dict[str, float]:
        """The variant's available numeric selected values by attribute."""
        async with sessionmaker()() as s:
            rows = await s.execute(
                select(m.SpecValue.attribute, m.SpecValue.value_num).where(
                    m.SpecValue.variant_id == variant_id, m.SpecValue.available, m.SpecValue.value_num.is_not(None)
                )
            )
            return {a: float(n) for a, n in rows.all() if n is not None}  # the query keeps numbers only

    @_store_errors
    async def accepted_transmissions(self, variant_id: str) -> list[str]:
        """The texts of the variant's accepted transmission claims."""
        async with sessionmaker()() as s:
            rows = await s.execute(
                select(m.Claim.value_text).where(
                    m.Claim.variant_id == variant_id, m.Claim.attribute == "transmission", m.Claim.status == "ACCEPTED"
                )
            )
            return [t for t in rows.scalars() if t is not None]

    @_store_errors
    async def set_gearbox(self, variant_id: str, family: str) -> None:
        """The variant's gearbox, only when it has none."""
        async with sessionmaker()() as s:
            v = await s.get(m.Variant, variant_id)
            if v is not None and not v.transmission:
                v.transmission = family
                await s.commit()

    @_store_errors
    async def replace_selected(self, variant_id: str, select_values: SelectValues) -> None:
        """Under the variant's advisory lock, in one transaction: the accepted claims and the schedule are read,
        `select_values` decides, the variant's `spec_values` are replaced."""
        async with sessionmaker()() as s:
            await s.execute(_LOCK, {"k": f"reselect:{variant_id}"})
            chosen = select_values(await _accepted_claims(s, variant_id), await _schedule(s, variant_id))
            await s.execute(delete(m.SpecValue).where(m.SpecValue.variant_id == variant_id))
            s.add_all([m.SpecValue(variant_id=variant_id, attribute=v.attribute, available=v.available,
                                   value_num=v.value_num, value_text=v.value_text, provenance=v.provenance,
                                   confidence=v.confidence, confidence_rule=v.confidence_rule,
                                   resolution_rule=v.resolution_rule, claim_ids=v.claim_ids,
                                   alternatives=v.alternatives) for v in chosen])  # fmt: skip
            await s.commit()


async def _accepted_claims(s: AsyncSession, variant_id: str) -> list[ev.ClaimIn]:
    rows = await s.execute(
        select(m.Claim, m.Evidence)
        .join(m.Evidence, m.Claim.evidence_id == m.Evidence.id)
        .where(m.Claim.variant_id == variant_id, m.Claim.status == "ACCEPTED")
    )
    return [ev.ClaimIn(c.id, c.attribute, c.value_num if c.value_num is not None else (c.value_text or ""),
                       e.source_type, e.domain, c.scope) for c, e in rows.all()]  # fmt: skip


async def _schedule(s: AsyncSession, variant_id: str) -> list[ScheduleItem]:
    items = list(
        (await s.execute(select(m.MaintenanceItem).where(m.MaintenanceItem.variant_id == variant_id))).scalars()
    )
    ids = {i for it in items for i in (it.evidence_ids or [])}
    urls: dict[str, str] = {}
    if ids:
        urls = {e.id: e.url for e in (await s.execute(select(m.Evidence).where(m.Evidence.id.in_(ids)))).scalars()}
    return [ScheduleItem(it.item, it.interval_km, it.interval_months,
                         tuple(urls.get(i, "") for i in (it.evidence_ids or []))) for it in items]  # fmt: skip
