"""The catalogue variants gold is loaded for (`vehicle_variants`, `research_jobs` for the recent ones): `Candidates`
over the database. Raises `GoldStoreUnavailable` when the database fails."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from automind.acquisition.gold.application.ports import GoldStoreUnavailable
from automind.acquisition.gold.domain.records import CandidateVariant
from automind.shared.infrastructure.db.errors import translate_errors
from automind.shared.infrastructure.db.models import ResearchJob, Variant
from automind.shared.infrastructure.db.session import sessionmaker

RECENT_DAYS = 30


class CandidateStore:
    """`Candidates` over the database."""

    @translate_errors(GoldStoreUnavailable)
    async def variants(self, make: str | None = None, recent: bool = False) -> list[CandidateVariant]:
        """Every variant (of `make`, any case; with `recent`, only those researched in the last 30 days)."""
        async with sessionmaker()() as s:
            q = select(Variant)
            if make:
                q = q.where(Variant.make.ilike(make))
            if recent:
                since = datetime.now(UTC) - timedelta(days=RECENT_DAYS)
                q = q.where(Variant.id.in_(select(ResearchJob.variant_id).where(ResearchJob.started_at >= since)))
            return [candidate(v) for v in (await s.execute(q)).scalars()]


def candidate(v: Variant) -> CandidateVariant:
    """A catalogue row as a candidate."""
    return CandidateVariant(
        id=v.id, make=v.make, model=v.model, generation=v.generation, variant_name=v.variant_name, fuel=v.fuel,
        powertrain=v.powertrain, power_kw=float(v.power_kw) if v.power_kw else None, engine_cc=v.engine_cc,
        years_from=v.generation_years_from, years_to=v.generation_years_to,
    )  # fmt: skip
