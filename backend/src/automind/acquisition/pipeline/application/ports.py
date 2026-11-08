"""The ports of the research pipeline's stores: the variant a job is about, a page's evidence and rows, the
selected values, the relevance verdicts and the job's own book (used pages, metrics, the area's run and sources).

Errors: every store raises `PipelineStoreUnavailable` when its database fails. A job catches it like any failure
(the job fails, the turn goes on, spec 002 FR-023); each write is one transaction, so a failed write leaves nothing
half-written (a page's evidence and its rows, a variant's selected values)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from automind.acquisition.pipeline.domain.hits import SourceKind, SourceRef
from automind.acquisition.pipeline.domain.rows import EvidenceIn, PageRow
from automind.acquisition.pipeline.domain.selection import ScheduleItem, SelectedValue
from automind.acquisition.pipeline.domain.variant import CarVariant
from automind.shared import evidence as ev
from automind.shared.contracts.json import JsonObject


class PipelineStoreUnavailable(RuntimeError):
    """A pipeline store could not read or write (its database); the cause is chained."""


class VariantStore(Protocol):
    """The variants a job is about."""

    async def load(self, variant_id: str) -> CarVariant | None:
        """The variant, None when there is none."""
        ...


class EvidenceStore(Protocol):
    """A page's evidence and the rows it gave."""

    async def save(self, evidence: EvidenceIn, rows: Sequence[PageRow] = ()) -> str:
        """The page's evidence row (its document found by content or stored) and its rows, in one transaction;
        returns the evidence id."""
        ...


class SelectValues(Protocol):
    """The rule that selects a variant's values (`domain.selection.select_values`)."""

    def __call__(self, claims: list[ev.ClaimIn], schedule: Sequence[ScheduleItem]) -> list[SelectedValue]:
        """The selected values from the accepted claims and the service schedule."""
        ...


class ValueStore(Protocol):
    """A variant's selected values, accepted transmission claims and gearbox."""

    async def known_values(self, variant_id: str) -> dict[str, float]:
        """The variant's available numeric selected values by attribute."""
        ...

    async def available(self, variant_id: str) -> set[str]:
        """The attributes the variant has an available selected value for (numeric or not)."""
        ...

    async def accepted_transmissions(self, variant_id: str) -> list[str]:
        """The texts of the variant's accepted transmission claims."""
        ...

    async def set_gearbox(self, variant_id: str, family: str) -> None:
        """The variant's gearbox, only when it has none."""
        ...

    async def replace_selected(self, variant_id: str, select: SelectValues) -> None:
        """Under the variant's lock and in one transaction: read the accepted claims and the schedule, call
        `select`, replace the variant's selected values with its result (parallel jobs recompute one at a time)."""
        ...


@dataclass(frozen=True)
class PageVerdict:
    """The relevance verdict on one page for one variant, with who gave it (rules, or the role's prompt and model)."""

    document_id: str
    variant_id: str
    verdict: str
    other: str | None
    reason: str
    method: str
    prompt_version: str | None
    model: str | None


class VerdictStore(Protocol):
    """The relevance verdicts per page and variant."""

    async def record(self, verdict: PageVerdict) -> None:
        """Store the verdict, replacing an earlier one on the same page and variant."""
        ...


@dataclass(frozen=True)
class JobMetrics:
    """What a job searched and read: its queries (JSON for the admin page) and page and value counts."""

    queries: list[JsonObject]
    pages_found: int
    pages_cached: int
    pages_rejected: dict[str, int]
    values_rejected: dict[str, int] | None
    reader_values: int


@dataclass(frozen=True)
class AreaRun:
    """The outcome of an area's research for a variant; `registry`: the job tried the registry's sources with the
    escalation to the other markets (else the earlier time is kept)."""

    variant_id: str
    area: str
    docs: int
    accepted: int
    rejected: int
    rounds: int
    minimum_met: bool
    registry: bool
    stage_versions: dict[str, str]


class JobBook(Protocol):
    """A job's book: used pages, metrics, the area's run and its accepted sources."""

    async def used_urls(self, variant_id: str) -> set[str]:
        """URLs already stored as the variant's evidence (never read again)."""
        ...

    async def record_metrics(self, job_id: str, metrics: JobMetrics) -> None:
        """The job row's metrics and its search cost so far; nothing when the job row is gone."""
        ...

    async def area_sources(self, variant_id: str, make: str, area: str, kind: SourceKind) -> list[SourceRef]:
        """The sources of the area's accepted values. Raises KeyError for an area with no store of its own."""
        ...

    async def mark_run(self, run: AreaRun, *, brand_positioning: bool = False) -> None:
        """Replace the area's run row; with `brand_positioning` (the manufacturer area) also set the make's
        positioning on all its variants from its stored facts (`selection.positioning_vote`), in one transaction."""
        ...


@dataclass(frozen=True)
class PipelineStores:
    """The stores a research job writes through."""

    variants: VariantStore
    evidence: EvidenceStore
    values: ValueStore
    verdicts: VerdictStore
    book: JobBook
