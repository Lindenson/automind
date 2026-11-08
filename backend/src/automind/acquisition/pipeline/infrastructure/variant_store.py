"""`vehicle_variants` as the pipeline reads them: a row becomes a `CarVariant`. Implements `ports.VariantStore`; a
database failure becomes `PipelineStoreUnavailable`."""

from __future__ import annotations

from automind.acquisition.pipeline.application.ports import PipelineStoreUnavailable
from automind.acquisition.pipeline.domain.variant import CarVariant, VariantFacts
from automind.shared.infrastructure.db.errors import translate_errors
from automind.shared.infrastructure.db.models import Variant
from automind.shared.infrastructure.db.session import sessionmaker

_store_errors = translate_errors(PipelineStoreUnavailable)


class VariantRepo:
    """The variants."""

    @_store_errors
    async def load(self, variant_id: str) -> CarVariant | None:
        """The variant, None when there is none."""
        async with sessionmaker()() as s:
            row = await s.get(Variant, variant_id)
            return variant_of(row) if row is not None else None


def variant_of(row: VariantFacts) -> CarVariant:
    """The record of a stored variant (or of anything that reads like one)."""
    return CarVariant(id=row.id, make=row.make, model=row.model, generation=row.generation,
                      variant_name=row.variant_name, powertrain=row.powertrain, body_class=row.body_class,
                      generation_years_from=row.generation_years_from, generation_years_to=row.generation_years_to,
                      transmission=row.transmission, drive=row.drive, market=row.market)  # fmt: skip
