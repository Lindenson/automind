"""The relevance verdict per page and variant (`page_relevance`), upserted. Implements `ports.VerdictStore`; a
database failure becomes `PipelineStoreUnavailable`."""

from __future__ import annotations

from dataclasses import asdict

from sqlalchemy.dialects.postgresql import insert

from automind.acquisition.pipeline.application.ports import PageVerdict, PipelineStoreUnavailable
from automind.shared.infrastructure.db.errors import translate_errors
from automind.shared.infrastructure.db.models import PageRelevance
from automind.shared.infrastructure.db.session import sessionmaker

_store_errors = translate_errors(PipelineStoreUnavailable)


class VerdictRepo:
    """Relevance verdicts."""

    @_store_errors
    async def record(self, verdict: PageVerdict) -> None:
        """Store the verdict, replacing an earlier one on the same page and variant."""
        values = asdict(verdict)
        async with sessionmaker()() as s:
            stmt = insert(PageRelevance).values(**values)
            await s.execute(stmt.on_conflict_do_update(index_elements=["document_id", "variant_id"], set_=values))
            await s.commit()
