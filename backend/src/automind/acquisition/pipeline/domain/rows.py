"""What one page leaves in the database, as records: the evidence row (its document found or created by content)
and the rows of what the page gave — spec claims and the items of the other areas. The store writes a page's
evidence and its rows in one transaction and fills in the evidence id; field names are the columns."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class EvidenceIn:
    """A page as evidence for a variant. `document_id` None: the store finds the document by its text (SHA-256) or
    stores it."""

    variant_id: str
    document_id: str | None
    url: str
    title: str
    text: str
    source_name: str
    domain: str
    source_type: str
    snippet_only: bool
    favourite_priority: int | None
    unverified: bool


@dataclass(frozen=True)
class ClaimRow:
    """One spec value as the page states it, with its check's status and who produced it."""

    variant_id: str
    attribute: str
    area: str
    raw_value: str
    raw_unit: str | None
    value_num: float | None
    value_text: str | None
    excerpt: str
    scope: str
    provenance: str
    status: str
    reject_rule: str | None
    extracted_by: str
    producer: str
    producer_version: str | None
    model: str | None
    snapshot_id: str | None


@dataclass(frozen=True)
class MaintenanceRow:
    """A service-schedule item: interval and sourced cost."""

    variant_id: str
    item: str
    interval_km: int | None
    interval_months: int | None
    cost_eur: float | None
    cost_basis: str
    excerpt: str


@dataclass(frozen=True)
class ReviewRow:
    """A pro or con of an expert or owner review."""

    variant_id: str
    polarity: str
    tag: str
    reviewer: str
    text: str
    excerpt: str


@dataclass(frozen=True)
class IssueRow:
    """A known issue of the car (reliability or used-car issues)."""

    variant_id: str
    component: str
    description: str
    age_from: int | None
    age_to: int | None
    mileage_from: int | None
    mileage_to: int | None
    severity_hint: str
    excerpt: str
    area: str


@dataclass(frozen=True)
class ReliabilityRow:
    """A reliability statistic of a survey or study."""

    variant_id: str
    source: str
    metric: str
    value: str
    year: int | None
    excerpt: str


@dataclass(frozen=True)
class BrandFactRow:
    """A fact about the make (not tied to the evidence row)."""

    make: str
    fact_type: str
    text: str
    positioning: str | None
    value_num: float | None
    year: int | None
    excerpt: str
    url: str
    source_name: str


@dataclass(frozen=True)
class UsedPriceRow:
    """An editorial used-price range in EUR, with its status."""

    variant_id: str
    model_year_from: int | None
    model_year_to: int | None
    min_eur: int
    max_eur: int
    market: str
    quoted_on: date | None
    excerpt: str
    status: str


@dataclass(frozen=True)
class RetentionRow:
    """A residual value after N years (share or amount)."""

    variant_id: str
    years: int
    share: float | None
    eur: float | None
    market: str
    quoted_on: date | None
    basis: str
    excerpt: str


PageRow = ClaimRow | MaintenanceRow | ReviewRow | IssueRow | ReliabilityRow | BrandFactRow | UsedPriceRow | RetentionRow
