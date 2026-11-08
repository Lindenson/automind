"""What the extractor, relevance and validator roles answer (web readers: text in, structured out, no tools; R8,
constitution VIII, XI): one pydantic schema per area and role. Every extracted item carries a verbatim excerpt
(`Excerpted`) that code checks against the document. The spec areas' claim schemas are built per area
(`areas.spec_claims_schema`)."""

from __future__ import annotations

from typing import Final, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field


@runtime_checkable
class AboutVariant(Protocol):
    """An extraction that says whether its page is about the target variant (the area schemas with the flag)."""

    is_about_variant: bool


class Excerpted(BaseModel):
    """An extracted item with the verbatim excerpt code checks against the document."""

    excerpt: str = Field(description="Verbatim sentence or table row from the document (copy exactly, ≤300 chars)")


class MaintenanceEntry(Excerpted):
    item: str
    interval_km: str | None = Field(default=None, description="As written, e.g. '15.000 km'")
    interval_months: str | None = Field(default=None, description="As written, e.g. '12 meses', '2 years'")
    cost_eur: str | None = Field(default=None, description="As written, only if the document states a cost")


class MaintenanceItems(BaseModel):
    is_about_variant: bool
    items: list[MaintenanceEntry]


class ReviewEntry(Excerpted):
    polarity: Literal["PRO", "CON"]
    tag: Literal["comfort", "handling", "quality", "practicality", "noise", "reliability", "value", "other"]
    reviewer: Literal["EXPERT", "OWNER"]
    text: str = Field(description="Neutral paraphrase, ≤25 words")


class ReviewItems(BaseModel):
    is_about_variant: bool
    items: list[ReviewEntry]


class IssueEntry(Excerpted):
    component: str
    description: str
    age_from: int | None = None
    age_to: int | None = None
    mileage_from: int | None = None
    mileage_to: int | None = None
    severity_hint: str = Field(default="", description="The document's own wording about seriousness")


class StatEntry(Excerpted):
    source: str
    metric: str
    value: str
    year: int | None = None


class IssueItems(BaseModel):
    is_about_variant: bool
    issues: list[IssueEntry]
    stats: list[StatEntry] = Field(default_factory=list)


FactType = Literal["HISTORY", "KEY_MODEL", "MARKET_POSITION", "MARKET_SHARE", "FINANCIAL", "RELIABILITY_REPUTATION",
                   "NETWORK_ES", "WARRANTY", "BATTERY_WARRANTY"]  # fmt: skip
# the members the pipeline checks (the schema the model sees stays a plain list of words)
NETWORK_ES: Final[FactType] = "NETWORK_ES"  # dealers and workshops in Spain: a count next to a network word
WARRANTIES: Final[tuple[FactType, ...]] = ("WARRANTY", "BATTERY_WARRANTY")  # plausible years only
MARKET_POSITION: Final[FactType] = "MARKET_POSITION"  # carries `positioning`


class ManufacturerEntry(Excerpted):
    fact_type: FactType
    text: str
    positioning: Literal["PREMIUM", "MAINSTREAM", "BUDGET"] | None = None
    value_num: float | None = Field(default=None, description="The key number of the fact, e.g. 6.1 (% share)")
    year: int | None = Field(default=None, description="The year the fact is about, e.g. 2025")


class ManufacturerFacts(BaseModel):
    is_about_variant: bool = True
    facts: list[ManufacturerEntry]


class UsedPriceEntry(Excerpted):
    model_year_from: int | None = None
    model_year_to: int | None = None
    min: float
    max: float
    currency: Literal["EUR", "GBP", "USD"] = "EUR"
    market: Literal["ES", "GB", "DE", "US"] = "ES"
    quoted_on: str | None = None


class UsedPriceItems(BaseModel):
    is_about_variant: bool = True
    ranges: list[UsedPriceEntry] = Field(default_factory=list)


class RetentionPoint(Excerpted):
    years: int = Field(description="Age in years the figure is for, e.g. 3 or 5")
    share_pct: float | None = Field(default=None, description="Value left as % of the new price, e.g. 58")
    eur: float | None = Field(default=None, description="Or the value left as an amount")
    currency: Literal["EUR", "GBP", "USD"] = "EUR"
    market: Literal["ES", "GB", "DE", "US", "EU"] = "ES"
    quoted_on: str | None = None


class DepreciationItems(BaseModel):
    """spec 004 FR-005: residual value / value retention after N years, from analysts and editorial sources."""

    is_about_variant: bool = True
    points: list[RetentionPoint] = Field(default_factory=list)


IncentiveKey = Literal["subsidy.purchase", "irpf.ev_deduction", "subsidy.region", "road_tax.reduction",
                       "label.zero.benefits", "charger.subsidy"]  # fmt: skip


class IncentiveEntry(Excerpted):
    """spec 006 FR-016: a Spanish incentive for electrified cars, with its dates."""

    key: IncentiveKey
    label: str = Field(description="Programme name as written, e.g. 'Plan MOVES III', 'Plan Auto+'")
    amount_eur: float | None = Field(default=None, description="Maximum amount for a private buyer of a car, EUR")
    percent: float | None = Field(default=None, description="A percentage (e.g. 15 for the IRPF deduction)")
    valid_from: str | None = Field(default=None, description="Start date YYYY-MM-DD if stated")
    valid_to: str | None = Field(default=None, description="End date YYYY-MM-DD if stated (deadline, expiry)")
    scope: Literal["national", "regional", "municipal"] = "national"
    region_code: str | None = Field(default=None, description="Region code for a regional plan, e.g. 'AN', 'MD'")
    powertrains: list[Literal["BEV", "PHEV", "EREV"]] = Field(default_factory=list)


class IncentiveFacts(BaseModel):
    facts: list[IncentiveEntry] = Field(default_factory=list)


# --- relevance role (spec 003 FR-013): only for pages the rules cannot decide -------------------


class RelevanceOut(BaseModel):
    verdict: Literal["RELEVANT", "MULTI_VARIANT", "OTHER_VARIANT", "NOT_ABOUT_CAR"]
    other: str | None = None
    reason: str = ""


# --- validator role (constitution XI) -----------------------------------------------------------


ClaimValidity = Literal["SAME_VARIANT", "GENERATION_WIDE", "OTHER_VARIANT", "OTHER_MARKET", "OTHER_YEAR", "UNCLEAR"]
GENERATION_WIDE: Final[ClaimValidity] = "GENERATION_WIDE"  # true of the whole generation: kept, LOW confidence


class Verdict(BaseModel):
    index: int
    verdict: ClaimValidity
    reason: str = ""


class Verdicts(BaseModel):
    verdicts: list[Verdict]
