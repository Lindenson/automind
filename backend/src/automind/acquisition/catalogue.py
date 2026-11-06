"""The catalogue (spec 012 T028): one row per real version of a car (`vehicle_variants`) and the makes' line-ups per
market (`brand_lineups`). The chat reads and adds versions here through `acquisition.api`; the bodies moved from
the chat's `resolve.py` / `lineup.py` unchanged.

One row per real version: a version is found by its canonical key, then by a near-identical name or the same
version under another name ("320d M Sport" vs "320d M Sport 8-speed automatic"); a found row has its blanks filled.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from rapidfuzz import fuzz
from sqlalchemy import func, select

from automind.acquisition.api.contracts import CatalogueVariant, StoredLineup, VariantDraft
from automind.shared.infrastructure import db
from automind.shared.infrastructure.config.settings import settings
from automind.shared.vehicle import identity

_FILLED = ("transmission", "drive", "trim", "trim_level", "price_eur")  # blanks of a found row the draft fills
_MATCHED = ("make", "model", "generation", "powertrain", "variant_name", "engine_cc", "power_kw", "transmission",
            "drive", "body_class", "trim", "fuel")  # the facts that tell two versions apart  # fmt: skip


async def catalogue_models(make: str) -> set[str]:
    """The model lines the catalogue has rows of for this make."""
    async with db.sessionmaker()() as s:
        rows = await s.execute(select(db.Variant.model).where(func.lower(db.Variant.make) == make.lower()).distinct())
        return {str(m) for m in rows.scalars()}


async def find_variants(make: str, model: str) -> list[CatalogueVariant]:
    """Every catalogued version of this make and model (any case)."""
    async with db.sessionmaker()() as s:
        rows = await s.execute(select(db.Variant).where(*_same_model(make, model)))
        return [view_of(v) for v in rows.scalars()]


async def get_variant(variant_id: str) -> CatalogueVariant | None:
    async with db.sessionmaker()() as s:
        v = await s.get(db.Variant, variant_id)
        return view_of(v) if v is not None else None


async def upsert_variant(draft: VariantDraft) -> CatalogueVariant:
    """The catalogue row of this version: the existing one (its blanks filled from the draft), else a new one."""
    async with db.sessionmaker()() as s:
        found = await _catalogued(s, draft)
        if found is not None:
            if found.generation_years_from is None and draft.generation_years_from:
                found.generation_years_from = draft.generation_years_from
                found.generation_years_to = draft.generation_years_to
            for col in _FILLED:
                if getattr(found, col) is None and getattr(draft, col) is not None:
                    setattr(found, col, getattr(draft, col))
            await s.commit()
            return view_of(found)
        v = db.Variant(
            canonical_key=draft.canonical_key, make=draft.make, model=draft.model, generation=draft.generation,
            variant_name=draft.variant_name, powertrain=draft.powertrain, body_class=draft.body_class,
            model_year_from=draft.generation_years_from, generation_years_from=draft.generation_years_from,
            generation_years_to=draft.generation_years_to, vehicle_class=draft.vehicle_class, segment=draft.segment,
            transmission=draft.transmission, drive=draft.drive, trim=(draft.trim or None) and draft.trim[:64],
            trim_level=draft.trim_level, price_eur=draft.price_eur,
            engine_cc=draft.engine_cc if draft.engine_cc and 600 <= draft.engine_cc <= 8000 else None,
            power_kw=draft.power_kw if draft.power_kw and 30 <= draft.power_kw <= 750 else None, fuel=draft.fuel,
        )  # fmt: skip
        s.add(v)
        await s.commit()
        return view_of(v)


async def stale_areas(variant_id: str, areas: tuple[str, ...]) -> list[str]:
    """The areas of a version never researched, or researched longer ago than their freshness allows."""
    async with db.sessionmaker()() as s:
        runs = {
            r.area: r
            for r in (await s.execute(select(db.ResearchRun).where(db.ResearchRun.variant_id == variant_id))).scalars()
        }
    out = []
    for area in areas:
        r = runs.get(area)
        if r is None or db.now() - r.completed_at > timedelta(days=settings().freshness_days(area)):
            out.append(area)
    return out


async def cached_lineup(make: str, market: str, ttl_days: int) -> StoredLineup | None:
    """The make's line-up on this market, unless older than `ttl_days`."""
    async with db.sessionmaker()() as s:
        row = (await s.execute(_lineup_row(make, market))).scalar_one_or_none()
    if row is None or row.fetched_at < datetime.now(UTC) - timedelta(days=ttl_days):
        return None
    return StoredLineup(make=make, market=market, models=list(row.models), sources=list(row.sources),
                        fetched_at=row.fetched_at)  # fmt: skip


async def store_lineup(lineup: StoredLineup) -> None:
    async with db.sessionmaker()() as s:
        row = (await s.execute(_lineup_row(lineup.make, lineup.market))).scalar_one_or_none()
        if row is None:
            row = db.BrandLineup(make=lineup.make, market=lineup.market)
            s.add(row)
        row.models, row.sources = lineup.models, lineup.sources
        row.fetched_at = lineup.fetched_at or datetime.now(UTC)
        await s.commit()


def view_of(v: db.Variant) -> CatalogueVariant:
    """A stored version as the chat reads it."""
    return CatalogueVariant(
        id=v.id, make=v.make, model=v.model, generation=v.generation, variant_name=v.variant_name,
        powertrain=v.powertrain, body_class=v.body_class, model_year_from=v.model_year_from, market=v.market or "ES",
        generation_years_from=v.generation_years_from, generation_years_to=v.generation_years_to,
        vehicle_class=v.vehicle_class, segment=v.segment, brand_positioning=v.brand_positioning,
        transmission=v.transmission, drive=v.drive, trim=v.trim, trim_level=v.trim_level,
        price_eur=float(v.price_eur) if v.price_eur is not None else None, engine_cc=v.engine_cc,
        power_kw=v.power_kw, fuel=v.fuel, created_at=v.created_at,
    )  # fmt: skip


def _same_model(make: str, model: str) -> tuple[Any, Any]:
    return func.lower(db.Variant.make) == make.lower(), func.lower(db.Variant.model) == model.lower()


async def _catalogued(s: Any, draft: VariantDraft) -> Any:
    """The row of this version: by key, by a near-identical name, or the same version under another name."""
    by_key = select(db.Variant).where(db.Variant.canonical_key == draft.canonical_key)
    found = (await s.execute(by_key)).scalar_one_or_none()
    if found is not None:
        return found
    new = {k: getattr(draft, k) for k in _MATCHED}
    for v in (await s.execute(select(db.Variant).where(*_same_model(draft.make, draft.model)))).scalars():
        old = view_of(v).model_dump()
        if identity.is_duplicate(old, new, fuzz.token_sort_ratio) or identity.same_version(
            old, new, trim_unknown_ok=False
        ):
            return v
    return None


def _lineup_row(make: str, market: str) -> Any:
    return select(db.BrandLineup).where(db.BrandLineup.make == make, db.BrandLineup.market == market)
