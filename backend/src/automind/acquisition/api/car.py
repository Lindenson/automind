"""Contracts of the car read model (spec 012 T028, research R13): what the engine has stored about one catalogued
version, as the chat's report reads it — selected values, accepted claims with their evidence, research runs,
issues, reviews, reliability figures, the make's facts, value retention, used prices, maintenance, rejected pages.
Data only; the field names are those of the stored rows, so a reader needs no other names."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from automind.acquisition.api.contracts import CatalogueVariant

__all__ = [
    "CarData",
    "ClaimRow",
    "EvidenceRow",
    "IssueRow",
    "MaintenanceRow",
    "ManufacturerFactRow",
    "RejectedPage",
    "ReliabilityStatRow",
    "ResearchRunRow",
    "RetentionRow",
    "ReviewRow",
    "SpecValueRow",
    "UsedPriceRow",
]


class SpecValueRow(BaseModel):
    """The value selected for one attribute (`spec_values`)."""

    attribute: str
    available: bool
    value_num: float | None = None
    value_text: str | None = None
    provenance: str | None = None
    confidence: str | None = None
    confidence_rule: str | None = None
    resolution_rule: str | None = None
    claim_ids: list[Any] = Field(default_factory=list)
    alternatives: list[Any] = Field(default_factory=list)
    updated_at: datetime | None = None


class EvidenceRow(BaseModel):
    id: str
    document_id: str
    url: str
    source_name: str
    domain: str
    source_type: str
    snippet_only: bool = False
    retrieved_at: datetime
    favourite: bool = False
    favourite_priority: int | None = None
    unverified: bool = False


class ClaimRow(BaseModel):
    """An accepted claim (`claims`)."""

    id: str
    evidence_id: str
    attribute: str
    area: str
    raw_value: str
    raw_unit: str | None = None
    value_num: float | None = None
    value_text: str | None = None
    excerpt: str
    scope: str
    provenance: str
    status: str
    extracted_by: str
    producer: str
    producer_version: str | None = None
    model: str | None = None


class ResearchRunRow(BaseModel):
    area: str
    completed_at: datetime
    docs_used: int = 0
    claims_accepted: int = 0
    claims_rejected: int = 0
    rounds_used: int = 0
    minimum_met: bool | None = None
    registry_at: datetime | None = None
    stage_versions: dict[str, Any] = Field(default_factory=dict)


class IssueRow(BaseModel):
    id: str
    component: str
    description: str
    age_from: int | None = None
    age_to: int | None = None
    mileage_from: int | None = None
    mileage_to: int | None = None
    severity_hint: str
    excerpt: str
    area: str
    evidence_id: str


class ReviewRow(BaseModel):
    id: str
    polarity: str
    tag: str
    reviewer: str
    text: str
    excerpt: str
    evidence_id: str


class ReliabilityStatRow(BaseModel):
    id: str
    source: str
    metric: str
    value: str
    year: int | None = None
    excerpt: str
    evidence_id: str


class ManufacturerFactRow(BaseModel):
    id: str
    make: str
    fact_type: str
    value_num: float | None = None
    year: int | None = None
    text: str
    positioning: str | None = None
    excerpt: str
    url: str
    source_name: str
    retrieved_at: datetime


class RetentionRow(BaseModel):
    """A sourced value share after `years` (numbers as stored: decimals)."""

    id: str
    evidence_id: str | None = None
    years: int
    share: Decimal | None = None
    eur: Decimal | None = None
    market: str
    quoted_on: date | None = None
    basis: str
    excerpt: str


class UsedPriceRow(BaseModel):
    """An accepted used-price range with the page it was read on."""

    min_eur: Decimal
    max_eur: Decimal
    model_year_from: int | None = None
    model_year_to: int | None = None
    url: str


class MaintenanceRow(BaseModel):
    item: str
    interval_km: int | None = None
    interval_months: int | None = None
    cost_eur: float | None = None
    cost_basis: str
    age_window: str | None = None
    evidence_ids: list[Any] = Field(default_factory=list)
    excerpt: str


class RejectedPage(BaseModel):
    """A page read for the car and judged to be about another car or none (newest first)."""

    title: str | None = None
    url: str
    final_url: str | None = None
    fetched_at: datetime | None = None
    retrieved_at: datetime
    reason: str | None = None
    other: str | None = None


class CarData(BaseModel):
    """Everything stored about one catalogued version."""

    variant: CatalogueVariant
    values: dict[str, SpecValueRow] = Field(default_factory=dict)
    claims: list[tuple[ClaimRow, EvidenceRow]] = Field(default_factory=list)
    runs: list[ResearchRunRow] = Field(default_factory=list)
    issues: list[tuple[IssueRow, EvidenceRow]] = Field(default_factory=list)
    used_issues: list[IssueRow] = Field(default_factory=list)  # area used_issues, for the ownership cost
    reviews: list[tuple[ReviewRow, EvidenceRow]] = Field(default_factory=list)
    stats: list[ReliabilityStatRow] = Field(default_factory=list)
    manufacturer_facts: list[ManufacturerFactRow] = Field(default_factory=list)
    retention: list[tuple[RetentionRow, EvidenceRow | None]] = Field(default_factory=list)
    used_prices: list[UsedPriceRow] = Field(default_factory=list)
    maintenance: list[MaintenanceRow] = Field(default_factory=list)
    rejected_pages: list[RejectedPage] = Field(default_factory=list)
