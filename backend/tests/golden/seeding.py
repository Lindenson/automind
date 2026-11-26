"""Spec 013: the caches a replayed chat saw — make line-ups (`brand_lineups`) and model versions
(`model_versions`) — seeded for one dialogue and restored after it; with either one the ports get the line-up
look-up and the versions store, so identification runs as in production."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select

from automind.shared.infrastructure.db import models as m
from automind.shared.infrastructure.db.session import sessionmaker

from .schema import Dialogue


def wire_identification(ports: Any, d: Dialogue) -> Any:
    """The ports with the line-up look-up and the versions store when the dialogue seeds either cache."""
    if not (d.lineups or d.model_versions):
        return ports
    from automind.chat.application.services.identification.lineup import get_lineup
    from automind.chat.infrastructure.persistence.repositories import ModelVersionsRepo

    return replace(ports, lineup=get_lineup, versions=ModelVersionsRepo())


async def seed_caches(d: Dialogue) -> Callable[[], Awaitable[None]]:
    """Replace the cached rows of the dialogue's makes / models by its own; returns the restore step."""
    now = datetime.now(UTC)
    async with sessionmaker()() as s:
        saved_lu = [await _take(s, m.BrandLineup, make=x.make, market=x.market) for x in d.lineups]
        saved_mv = [await _take(s, m.ModelVersions, make=x.make, model=x.model, market="ES") for x in d.model_versions]
        for x in d.lineups:
            s.add(m.BrandLineup(make=x.make, market=x.market, models=x.models, sources=x.sources, fetched_at=now))
        for g in d.model_versions:
            s.add(m.ModelVersions(make=g.make, model=g.model, generation=g.generation, market="ES",
                                  years_from=g.years_from, years_to=g.years_to, body_class=g.body_class,
                                  versions=g.versions, sources=g.sources, fetched_at=now))  # fmt: skip
        await s.commit()

    async def restore() -> None:
        async with sessionmaker()() as s:
            for x in d.lineups:
                await s.execute(delete(m.BrandLineup).where(m.BrandLineup.make == x.make,
                                                            m.BrandLineup.market == x.market))  # fmt: skip
            for g in d.model_versions:
                await s.execute(delete(m.ModelVersions).where(m.ModelVersions.make == g.make,
                                                              m.ModelVersions.model == g.model))  # fmt: skip
            for rows in (*saved_lu, *saved_mv):
                for row in rows:
                    s.add(row)
            await s.commit()

    return restore


async def _take(s: Any, table: Any, **where: str) -> list[Any]:
    """Remove the rows of `table` matching `where` and return detached copies to put back later."""
    q = select(table).where(*(getattr(table, k) == v for k, v in where.items()))
    rows = (await s.execute(q)).scalars().all()
    cols = [c.key for c in table.__table__.columns]
    copies = [table(**{c: getattr(r, c) for c in cols}) for r in rows]
    for r in rows:
        await s.delete(r)
    await s.flush()
    return copies
