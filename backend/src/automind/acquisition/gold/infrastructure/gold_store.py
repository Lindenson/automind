"""Gold persistence (spec 011 FR-003, data-model "Migration 0019"): `GoldStore` is the `GoldBook` over
`gold_datasets` and `gold_values`. Every method is one transaction and raises `GoldStoreUnavailable` when the
database fails."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from automind.acquisition.gold.application.ports import GoldStoreUnavailable
from automind.acquisition.gold.domain.choice import best_by_attribute
from automind.acquisition.gold.domain.records import DatasetInfo, GoldValue, StoredGold
from automind.shared.contracts.json import JsonObject
from automind.shared.infrastructure.db.errors import translate_errors
from automind.shared.infrastructure.db.models import GoldDataset, GoldValueRow, uid
from automind.shared.infrastructure.db.session import sessionmaker

_KEY = ("id", "variant_id", "attribute", "origin", "dataset_id")  # uq_gold_values (with the id)


class GoldStore:
    """`GoldBook` over the database."""

    @translate_errors(GoldStoreUnavailable)
    async def record_load(self, info: DatasetInfo, rows_read: int = 0, rows_matched: int = 0) -> None:
        """Record a load of `info`: now, the counts and the next refresh (given, or `refresh_days` from now)."""
        now = datetime.now(UTC)
        refresh = info.next_refresh_at
        if refresh is None and info.refresh_days:
            refresh = now + timedelta(days=int(info.refresh_days))
        values: JsonObject = {
            "name": info.name, "kind": info.kind, "version": info.version, "licence": info.licence, "url": info.url,
            "rows_read": rows_read, "rows_matched": rows_matched, "error": None, "loaded_at": now,
            "next_refresh_at": refresh,
        }  # fmt: skip
        async with sessionmaker()() as s:
            stmt = insert(GoldDataset).values(id=info.id, **values)
            await s.execute(stmt.on_conflict_do_update(index_elements=["id"], set_=values))
            await s.commit()

    @translate_errors(GoldStoreUnavailable)
    async def replace(self, dataset_id: str, variant_id: str, gold: Iterable[GoldValue]) -> int:
        """The gold values of one dataset for one variant: the newest load replaces the previous one."""
        rows = [_row(g, datetime.now(UTC)) for g in gold]
        async with sessionmaker()() as s:
            await s.execute(
                delete(GoldValueRow).where(GoldValueRow.dataset_id == dataset_id, GoldValueRow.variant_id == variant_id)
            )
            if rows:
                await s.execute(insert(GoldValueRow).values(rows))
            await s.commit()
        return len(rows)

    @translate_errors(GoldStoreUnavailable)
    async def put(self, gold: GoldValue) -> None:
        """One gold value (challenges): replaces the value of the same variant, attribute, origin and dataset."""
        row = _row(gold, datetime.now(UTC))
        async with sessionmaker()() as s:
            stmt = insert(GoldValueRow).values(**row)
            keep = {k: v for k, v in row.items() if k not in _KEY}
            await s.execute(stmt.on_conflict_do_update(constraint="uq_gold_values", set_=keep))
            await s.commit()

    @translate_errors(GoldStoreUnavailable)
    async def stored(self, variant_id: str, include_flagged: bool = False) -> list[StoredGold]:
        """The variant's gold; flagged gold is left out unless asked for."""
        async with sessionmaker()() as s:
            q = select(GoldValueRow).where(GoldValueRow.variant_id == variant_id)
            if not include_flagged:
                q = q.where(GoldValueRow.flagged.is_(False))
            return [_stored(r) for r in (await s.execute(q)).scalars()]

    async def best(self, variant_id: str) -> dict[str, StoredGold]:
        """The best unflagged gold of each attribute of the variant."""
        return best_by_attribute(await self.stored(variant_id))


def _row(g: GoldValue, now: datetime) -> JsonObject:
    return {
        "id": uid(), "variant_id": g.variant_id, "attribute": g.attribute, "value_num": g.value_num,
        "value_text": g.value_text, "unit": g.unit, "tolerance": g.tolerance, "tolerance_kind": g.tolerance_kind,
        "origin": g.origin, "dataset_id": g.dataset_id, "record_key": g.record_key, "match_rule": g.match_rule,
        "confidence": g.confidence, "registrations": g.registrations, "verified_at": now, "flagged": False,
        "flag_reason": None, "details": g.details or {},
    }  # fmt: skip


def _stored(r: GoldValueRow) -> StoredGold:
    return StoredGold(
        id=r.id, variant_id=r.variant_id, attribute=r.attribute, value_num=r.value_num, value_text=r.value_text,
        unit=r.unit, tolerance=r.tolerance, tolerance_kind=r.tolerance_kind, origin=r.origin,
        match_rule=r.match_rule, confidence=r.confidence, dataset_id=r.dataset_id, verified_at=r.verified_at,
    )  # fmt: skip
