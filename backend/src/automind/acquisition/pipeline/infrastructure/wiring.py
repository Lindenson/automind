"""The pipeline's stores over the database, and the services built on them."""

from __future__ import annotations

from automind.acquisition.pipeline.application.ports import PipelineStores
from automind.acquisition.pipeline.application.selection import ValueSelection
from automind.acquisition.pipeline.infrastructure.evidence_store import EvidenceRepo
from automind.acquisition.pipeline.infrastructure.job_book import JobBookRepo
from automind.acquisition.pipeline.infrastructure.value_store import ValueRepo
from automind.acquisition.pipeline.infrastructure.variant_store import VariantRepo
from automind.acquisition.pipeline.infrastructure.verdict_store import VerdictRepo


def stores() -> PipelineStores:
    """The stores a research job writes through."""
    return PipelineStores(variants=VariantRepo(), evidence=EvidenceRepo(), values=ValueRepo(), verdicts=VerdictRepo(),
                          book=JobBookRepo())  # fmt: skip


def value_selection() -> ValueSelection:
    """Selected values and gearbox of a variant."""
    return ValueSelection(ValueRepo())
