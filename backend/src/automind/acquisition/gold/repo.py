"""Gold persistence (spec 011 FR-003, data-model "Migration 0019").

`upsert_dataset()` records a dataset load; `replace()` writes the gold values of one (dataset, variant), replacing
the previous load. Loaders (`gold/loaders/*`) produce `DatasetRow`s; `gold/load.py` matches them and calls these.
`gold_for()` serves replay and signals: flagged gold is left out unless asked for.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert

from automind.acquisition.gold.domain.match import GoldValue
from automind.acquisition.infrastructure import config as acq_config
from automind.shared.infrastructure.db import GoldDataset, GoldValueRow, sessionmaker, uid
from automind.shared.vehicle import specs

CHALLENGES = "challenges"  # gold_datasets.id of user challenges
REFERENCE_SET = "reference_set"
_CONFIDENCE_RANK = {"HIGH": 0, "MEDIUM": 1}
_ORIGIN_RANK = {"reference_set": 0, "dataset": 1, "challenge": 2}


@dataclass(frozen=True)
class DatasetInfo:
    """A dataset that is not loaded by a dataset loader (reference set, challenges). The loaders describe theirs
    with `gold.loaders.DatasetMeta` (same fields, `next_refresh_at` instead of `refresh_days`)."""

    id: str  # e.g. "reference_set", "challenges"
    name: str
    kind: str  # reference_set | challenge
    licence: str  # internal
    url: str | None = None
    version: str | None = None
    refresh_days: int | None = None


async def upsert_dataset(info: Any, rows_read: int = 0, rows_matched: int = 0, error: str | None = None) -> None:
    """Record a load of `info` (a `DatasetInfo` or the loaders' `DatasetMeta`)."""
    now = datetime.now(UTC)
    refresh = getattr(info, "next_refresh_at", None)
    if refresh is None and getattr(info, "refresh_days", None):
        refresh = now + timedelta(days=int(info.refresh_days))
    values: dict[str, Any] = {
        "name": info.name, "kind": info.kind, "version": info.version, "licence": info.licence, "url": info.url,
        "rows_read": rows_read, "rows_matched": rows_matched, "error": error,
        "loaded_at": now if error is None else None, "next_refresh_at": refresh,
    }  # fmt: skip
    if error is not None:  # a failed load keeps the last good load's time and counts
        values = {k: v for k, v in values.items() if k in ("name", "kind", "licence", "url", "error")}
    async with sessionmaker()() as s:
        stmt = insert(GoldDataset).values(id=info.id, **{**values, "name": info.name, "licence": info.licence})
        await s.execute(stmt.on_conflict_do_update(index_elements=["id"], set_=values))
        await s.commit()


def _row(g: GoldValue, now: datetime) -> dict[str, Any]:
    return {
        "id": uid(), "variant_id": g.variant_id, "attribute": g.attribute, "value_num": g.value_num,
        "value_text": g.value_text, "unit": g.unit, "tolerance": g.tolerance, "tolerance_kind": g.tolerance_kind,
        "origin": g.origin, "dataset_id": g.dataset_id, "record_key": g.record_key, "match_rule": g.match_rule,
        "confidence": g.confidence, "registrations": g.registrations, "verified_at": now, "flagged": False,
        "flag_reason": None, "details": g.details or {},
    }  # fmt: skip


async def replace(dataset_id: str, variant_id: str, gold: Iterable[GoldValue]) -> int:
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


async def upsert_value(g: GoldValue) -> None:
    """One gold value (challenges): replaces the value of the same variant, attribute, origin and dataset."""
    row = _row(g, datetime.now(UTC))
    async with sessionmaker()() as s:
        stmt = insert(GoldValueRow).values(**row)
        keep = {k: v for k, v in row.items() if k not in ("id", "variant_id", "attribute", "origin", "dataset_id")}
        await s.execute(stmt.on_conflict_do_update(constraint="uq_gold_values", set_=keep))
        await s.commit()


async def gold_for(variant_id: str, include_flagged: bool = False) -> list[GoldValueRow]:
    async with sessionmaker()() as s:
        q = select(GoldValueRow).where(GoldValueRow.variant_id == variant_id)
        if not include_flagged:
            q = q.where(GoldValueRow.flagged.is_(False))
        return list((await s.execute(q)).scalars())


def best_by_attribute(rows: Iterable[GoldValueRow]) -> dict[str, GoldValueRow]:
    """One gold value per attribute: HIGH before MEDIUM, then reference set, dataset, challenge; newest first."""
    best: dict[str, GoldValueRow] = {}
    for r in sorted(rows, key=lambda r: r.verified_at, reverse=True):
        cur = best.get(r.attribute)
        rank = (_CONFIDENCE_RANK.get(r.confidence, 9), _ORIGIN_RANK.get(r.origin, 9))
        if cur is None or rank < (_CONFIDENCE_RANK.get(cur.confidence, 9), _ORIGIN_RANK.get(cur.origin, 9)):
            best[r.attribute] = r
    return best


async def flag(gold_id: str, flagged: bool, reason: str | None) -> None:
    """Mark (or clear) a gold value contradicted by several independent families (research R3)."""
    async with sessionmaker()() as s:
        await s.execute(
            update(GoldValueRow).where(GoldValueRow.id == gold_id).values(flagged=flagged, flag_reason=reason)
        )
        await s.commit()


def tolerance_of(attribute: str) -> tuple[str, float]:
    """(kind, tolerance) of an attribute: config/gold_datasets.yaml, else the attribute's own relative tolerance."""
    tols = acq_config.gold_tolerances()
    if attribute in tols:
        return tols[attribute]
    a = specs.ATTRS.get(attribute)
    return ("rel", float(a.tolerance)) if a is not None else ("rel", 0.03)


def unit_of(attribute: str) -> str:
    """The attribute's unit: as the datasets publish it (config/gold_datasets.yaml), else the canonical one."""
    units: dict[str, Any] = {}
    for d in (acq_config.gold_datasets_config().get("datasets") or {}).values():
        units = {**(d.get("units") or {}), **units}
    a = specs.ATTRS.get(attribute)
    return str(units.get(attribute) or (a.unit if a is not None and a.unit else ""))


async def record_challenge(
    variant_id: str, attribute: str, outcome: str, value: str | float | None, challenge_id: str | None,
    unit: str | None = None,
) -> bool:  # fmt: skip
    """A CONFIRMED or CORRECTED user challenge becomes gold (origin `challenge`, MEDIUM until a dataset agrees)."""
    if outcome not in ("CONFIRMED", "CORRECTED") or value is None or str(value).strip() == "":
        return False
    num: float | None
    try:
        num, text = float(str(value).replace(",", ".")), None
    except ValueError:
        num, text = None, str(value)
    await upsert_dataset(DatasetInfo(CHALLENGES, "User challenges (confirmed or corrected)", "challenge", "internal"))
    kind, tol = tolerance_of(attribute)
    await upsert_value(
        GoldValue(
            variant_id=variant_id,
            attribute=attribute,
            value_num=num,
            value_text=text,
            unit=unit or unit_of(attribute),
            tolerance=tol,
            tolerance_kind=kind,
            origin="challenge",
            match_rule=f"challenge_{outcome.lower()}",
            confidence="MEDIUM",
            dataset_id=CHALLENGES,
            record_key=challenge_id,
        )  # fmt: skip
    )
    return True
