"""Persistence: catalog/cache, evidence, claims, selected spec values, chat history, LLM usage."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def now() -> datetime:
    return datetime.now(timezone.utc)


def uid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class Variant(Base):
    __tablename__ = "vehicle_variants"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    canonical_key: Mapped[str] = mapped_column(String(400), unique=True)
    make: Mapped[str] = mapped_column(String(80))
    model: Mapped[str] = mapped_column(String(120))
    generation: Mapped[str | None] = mapped_column(String(80))
    variant_name: Mapped[str] = mapped_column(String(200))
    powertrain: Mapped[str] = mapped_column(String(8))
    body_class: Mapped[str | None] = mapped_column(String(20))
    model_year_from: Mapped[int | None] = mapped_column(Integer)
    market: Mapped[str] = mapped_column(String(2), default="ES")
    generation_years_from: Mapped[int | None] = mapped_column(Integer)
    generation_years_to: Mapped[int | None] = mapped_column(Integer)
    vehicle_class: Mapped[str | None] = mapped_column("class", String(20))  # small|compact|mid_large|premium_suv_4x4
    segment: Mapped[str | None] = mapped_column(String(40))
    brand_positioning: Mapped[str | None] = mapped_column(String(12))  # PREMIUM|MAINSTREAM|BUDGET (sourced)
    # spec 004: gearbox and driven wheels when a model is sold with several (FR-028); equipment level (FR-029)
    transmission: Mapped[str | None] = mapped_column(String(16))  # manual|automatic|dct|cvt|e-cvt|single
    drive: Mapped[str | None] = mapped_column(String(4))  # FWD | RWD | AWD
    trim: Mapped[str | None] = mapped_column(String(64))  # equipment name, e.g. "Klass", "Homura"
    trim_level: Mapped[str | None] = mapped_column(String(4))  # BASE | MID | TOP
    price_eur: Mapped[float | None] = mapped_column(Numeric(10, 0))  # official price of this version (ES)
    # spec 005: the engine is part of the identity (research R4)
    engine_cc: Mapped[int | None] = mapped_column(Integer)  # 600–8000
    power_kw: Mapped[int | None] = mapped_column(Integer)  # 30–750
    fuel: Mapped[str | None] = mapped_column(String(8))  # petrol|diesel|hybrid|mhev|phev|bev|lpg
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    @property
    def label(self) -> str:
        gen = f" {self.generation}" if self.generation else ""
        return f"{self.make} {self.model}{gen} {self.variant_name}".replace("  ", " ").strip()


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    url: Mapped[str] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    content_sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    # page store (spec 003, data-model "documents → page store"): one row per normalised URL
    url_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    final_url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="OK", server_default="OK")  # OK|NO_CONTENT|REFUSED|ERROR
    fail_reason: Mapped[str | None] = mapped_column(Text)
    content_type: Mapped[str | None] = mapped_column(String(60))
    reader: Mapped[str | None] = mapped_column(String(40))  # main_content | pdf | site:<id>
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    bytes: Mapped[int | None] = mapped_column(Integer)


class Evidence(Base):
    __tablename__ = "evidence"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    variant_id: Mapped[str] = mapped_column(ForeignKey("vehicle_variants.id"), index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"))
    url: Mapped[str] = mapped_column(Text)
    source_name: Mapped[str] = mapped_column(String(200))
    domain: Mapped[str] = mapped_column(String(200))
    source_type: Mapped[str] = mapped_column(String(24))
    snippet_only: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    favourite: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    favourite_priority: Mapped[int | None] = mapped_column(Integer)


class Claim(Base):
    __tablename__ = "claims"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    variant_id: Mapped[str] = mapped_column(ForeignKey("vehicle_variants.id"), index=True)
    evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence.id"))
    attribute: Mapped[str] = mapped_column(String(40))
    area: Mapped[str] = mapped_column(String(20), default="specs", server_default="specs")
    raw_value: Mapped[str] = mapped_column(Text)
    raw_unit: Mapped[str | None] = mapped_column(String(40))
    value_num: Mapped[float | None] = mapped_column(Float)
    value_text: Mapped[str | None] = mapped_column(Text)
    excerpt: Mapped[str] = mapped_column(Text)
    scope: Mapped[str] = mapped_column(String(12), default="VARIANT")
    provenance: Mapped[str] = mapped_column(String(24))
    # ACCEPTED | REJECTED_UNSUPPORTED | REJECTED_UNIT | REJECTED_IMPLAUSIBLE | REJECTED_OTHER_VARIANT
    # | REJECTED_OTHER_MARKET | REJECTED_OTHER_YEAR | REJECTED_AMBIGUOUS
    status: Mapped[str] = mapped_column(String(32))
    reject_rule: Mapped[str | None] = mapped_column(String(40))
    extracted_by: Mapped[str] = mapped_column(String(12), default="LLM", server_default="LLM")  # READER | LLM
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class SpecValue(Base):
    __tablename__ = "spec_values"
    __table_args__ = (UniqueConstraint("variant_id", "attribute"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    variant_id: Mapped[str] = mapped_column(ForeignKey("vehicle_variants.id"), index=True)
    attribute: Mapped[str] = mapped_column(String(40))
    available: Mapped[bool] = mapped_column(default=False)
    value_num: Mapped[float | None] = mapped_column(Float)
    value_text: Mapped[str | None] = mapped_column(Text)
    provenance: Mapped[str | None] = mapped_column(String(24))
    confidence: Mapped[str | None] = mapped_column(String(8))
    confidence_rule: Mapped[str | None] = mapped_column(String(40))
    resolution_rule: Mapped[str | None] = mapped_column(String(40))
    claim_ids: Mapped[list] = mapped_column(JSON, default=list)
    alternatives: Mapped[list] = mapped_column(JSON, default=list)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ResearchRun(Base):
    """Cache freshness per (variant, area)."""

    __tablename__ = "research_runs"
    __table_args__ = (UniqueConstraint("variant_id", "area"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    variant_id: Mapped[str] = mapped_column(ForeignKey("vehicle_variants.id"), index=True)
    area: Mapped[str] = mapped_column(String(20))
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    docs_used: Mapped[int] = mapped_column(Integer, default=0)
    claims_accepted: Mapped[int] = mapped_column(Integer, default=0)
    claims_rejected: Mapped[int] = mapped_column(Integer, default=0)
    rounds_used: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    minimum_met: Mapped[bool | None] = mapped_column(Boolean)


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    chat_id: Mapped[str] = mapped_column(String(36), index=True)
    turn_id: Mapped[str | None] = mapped_column(String(36), index=True)
    role: Mapped[str] = mapped_column(String(10))
    text: Mapped[str] = mapped_column(Text)
    blocks: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class LLMCall(Base):
    __tablename__ = "llm_calls"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    chat_id: Mapped[str | None] = mapped_column(String(36), index=True)
    turn_id: Mapped[str | None] = mapped_column(String(36), index=True)
    job_id: Mapped[str | None] = mapped_column(String(36), index=True)
    area: Mapped[str | None] = mapped_column(String(20))
    role: Mapped[str] = mapped_column(String(20))
    model: Mapped[str] = mapped_column(String(80))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    cost_eur: Mapped[float | None] = mapped_column(Numeric(10, 5))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


# --- Conversation (spec 002, data-model §1-2) -------------------------------------------------


class Chat(Base):
    __tablename__ = "chats"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)  # also the LangGraph thread_id
    title: Mapped[str] = mapped_column(String(60), default="New chat")
    language: Mapped[str | None] = mapped_column(String(8))
    owner: Mapped[str | None] = mapped_column(String(64), index=True)  # SHA-256 of the browser's owner cookie
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class CaseFileRow(Base):
    __tablename__ = "case_files"
    __table_args__ = (PrimaryKeyConstraint("chat_id", "version"),)
    chat_id: Mapped[str] = mapped_column(String(36))
    version: Mapped[int] = mapped_column(Integer)
    data: Mapped[dict] = mapped_column(JSONB)
    changed_by: Mapped[str] = mapped_column(String(8))  # user | hub
    change_log: Mapped[list] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


TURN_ACTIONS = (
    "ANSWER_GENERAL",
    "ASK",
    "CONFIRM_VARIANTS",
    "CONFIRM_COST",
    "RESEARCH",
    "ANSWER_FROM_CONTEXT",
    "REPORT",
)
TURN_STATUSES = ("RUNNING", "WAITING_CONFIRMATION", "DONE", "CANCELLED", "FAILED")


class Turn(Base):
    __tablename__ = "turns"
    __table_args__ = (
        UniqueConstraint("chat_id", "seq"),
        # one RUNNING turn per chat (migration 0009, ADR-026)
        Index("uq_turns_one_running_per_chat", "chat_id", unique=True, postgresql_where=text("status = 'RUNNING'")),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    chat_id: Mapped[str] = mapped_column(String(36), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    user_message_id: Mapped[str | None] = mapped_column(String(36))
    request_kind: Mapped[str | None] = mapped_column(String(24))
    action: Mapped[str | None] = mapped_column(String(24))
    case_version_before: Mapped[int | None] = mapped_column(Integer)
    case_version_after: Mapped[int | None] = mapped_column(Integer)
    fingerprint: Mapped[str | None] = mapped_column(String(64))
    cost_estimate_eur: Mapped[float | None] = mapped_column(Numeric(10, 4))
    usage: Mapped[dict] = mapped_column(JSONB, default=dict)
    limits_reached: Mapped[list] = mapped_column(JSONB, default=list)
    status: Mapped[str] = mapped_column(String(24), default="RUNNING")
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TurnEvent(Base):
    __tablename__ = "turn_events"
    __table_args__ = (PrimaryKeyConstraint("chat_id", "seq"),)
    chat_id: Mapped[str] = mapped_column(String(36))
    seq: Mapped[int] = mapped_column(BigInteger)
    turn_id: Mapped[str | None] = mapped_column(String(36))
    type: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


JOB_STATUSES = ("PENDING", "RUNNING", "DONE", "FAILED", "SKIPPED")


class ResearchJob(Base):
    __tablename__ = "research_jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    chat_id: Mapped[str] = mapped_column(String(36), index=True)
    turn_id: Mapped[str] = mapped_column(String(36), index=True)
    variant_id: Mapped[str] = mapped_column(ForeignKey("vehicle_variants.id"))
    area: Mapped[str] = mapped_column(String(20))
    round: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(10), default="PENDING")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    docs: Mapped[int] = mapped_column(Integer, default=0)
    accepted: Mapped[int] = mapped_column(Integer, default=0)
    rejected: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # spec 003 metrics (FR-017)
    queries: Mapped[list[Any] | None] = mapped_column(JSONB)
    pages_found: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    pages_cached: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    pages_rejected: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    values_rejected: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    reader_values: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    search_cost_eur: Mapped[float | None] = mapped_column(Numeric(10, 4))


class SearchCall(Base):
    __tablename__ = "search_calls"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    chat_id: Mapped[str | None] = mapped_column(String(36), index=True)
    turn_id: Mapped[str | None] = mapped_column(String(36), index=True)
    job_id: Mapped[str | None] = mapped_column(String(36), index=True)
    area: Mapped[str | None] = mapped_column(String(20))
    provider: Mapped[str] = mapped_column(String(20), default="tavily")
    kind: Mapped[str] = mapped_column(String(10))  # search | extract
    credits: Mapped[float] = mapped_column(Float, default=0)
    cost_eur: Mapped[float | None] = mapped_column(Numeric(10, 5))
    cached: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


# --- Search v2: cache, relevance, used prices, reader stats, feasibility, tombstones (spec 003) -----


class SearchCache(Base):
    __tablename__ = "search_cache"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider: Mapped[str] = mapped_column(String(20))
    query: Mapped[str] = mapped_column(Text)
    gl: Mapped[str] = mapped_column(String(8))
    hl: Mapped[str] = mapped_column(String(8))
    hits: Mapped[list[Any]] = mapped_column(JSONB)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    empty: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))


class LearnedSource(Base):
    """A domain that keeps giving accepted values for an area and market (spec 007 FR-022)."""

    __tablename__ = "learned_sources"
    __table_args__ = (UniqueConstraint("domain", "area", "market", name="uq_learned_source"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    domain: Mapped[str] = mapped_column(String(253))
    area: Mapped[str] = mapped_column(String(40))
    market: Mapped[str] = mapped_column(String(8))
    source_type: Mapped[str] = mapped_column(String(30))
    accepted_runs: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    misses: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class MarketFact(Base):
    """A market-level fact with dates and evidence (spec 006 FR-016): subsidies, tax deductions, label benefits.
    `value`: {amount_eur?, percent?, text, label, scope: national|regional|municipal, region_code?, url}."""

    __tablename__ = "market_facts"
    __table_args__ = (UniqueConstraint("market", "key", name="uq_market_fact"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    market: Mapped[str] = mapped_column(String(4))
    key: Mapped[str] = mapped_column(String(60))
    value: Mapped[dict[str, Any]] = mapped_column(JSONB)
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    evidence_ids: Mapped[list[str]] = mapped_column(JSONB)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class PageRelevance(Base):
    __tablename__ = "page_relevance"
    __table_args__ = (PrimaryKeyConstraint("document_id", "variant_id"),)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    variant_id: Mapped[str] = mapped_column(ForeignKey("vehicle_variants.id"))
    verdict: Mapped[str] = mapped_column(String(16))  # RELEVANT|OTHER_VARIANT|MULTI_VARIANT|NOT_ABOUT_CAR|UNCERTAIN
    other: Mapped[str | None] = mapped_column(String(80))
    reason: Mapped[str] = mapped_column(Text)
    method: Mapped[str] = mapped_column(String(12))  # RULES | LLM
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class UsedPriceRange(Base):
    __tablename__ = "used_price_ranges"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    variant_id: Mapped[str] = mapped_column(ForeignKey("vehicle_variants.id"), index=True)
    evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence.id"))
    model_year_from: Mapped[int | None] = mapped_column(Integer)
    model_year_to: Mapped[int | None] = mapped_column(Integer)
    min_eur: Mapped[float] = mapped_column(Numeric(10, 0))
    max_eur: Mapped[float] = mapped_column(Numeric(10, 0))
    market: Mapped[str] = mapped_column(String(4))
    quoted_on: Mapped[date | None] = mapped_column(Date)
    excerpt: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class SiteReaderStat(Base):
    __tablename__ = "site_reader_stats"
    __table_args__ = (PrimaryKeyConstraint("domain", "day"),)
    domain: Mapped[str] = mapped_column(String(200))
    day: Mapped[date] = mapped_column(Date)
    ok: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    ambiguous: Mapped[int] = mapped_column(Integer, default=0)


class FeasibilityCheck(Base):
    __tablename__ = "feasibility_checks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    chat_id: Mapped[str] = mapped_column(String(36), index=True)
    turn_id: Mapped[str] = mapped_column(String(36))
    variant_id: Mapped[str] = mapped_column(ForeignKey("vehicle_variants.id"))
    check: Mapped[str] = mapped_column(String(16))  # BUDGET|RUNNING_COST|USAGE_SPACE|USAGE_POWER|USAGE_RANGE
    verdict: Mapped[str] = mapped_column(String(16))  # FITS|DOES_NOT_FIT|USED_ONLY|OTHER_CLASS|UNKNOWN
    details: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class DeletedChat(Base):
    __tablename__ = "deleted_chats"
    chat_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    deleted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    counts: Mapped[dict[str, Any]] = mapped_column(JSONB)


# --- Research results per area (data-model §4) ------------------------------------------------


class MaintenanceItem(Base):
    __tablename__ = "maintenance_items"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    variant_id: Mapped[str] = mapped_column(ForeignKey("vehicle_variants.id"), index=True)
    item: Mapped[str] = mapped_column(Text)
    interval_km: Mapped[int | None] = mapped_column(Integer)
    interval_months: Mapped[int | None] = mapped_column(Integer)
    cost_eur: Mapped[float | None] = mapped_column(Float)
    cost_basis: Mapped[str] = mapped_column(String(12), default="SOURCED")  # SOURCED | ASSUMPTION
    age_window: Mapped[str | None] = mapped_column(String(40))
    evidence_ids: Mapped[list] = mapped_column(JSONB, default=list)
    excerpt: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ReviewItem(Base):
    __tablename__ = "review_items"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    variant_id: Mapped[str] = mapped_column(ForeignKey("vehicle_variants.id"), index=True)
    polarity: Mapped[str] = mapped_column(String(4))  # PRO | CON
    tag: Mapped[str] = mapped_column(String(16))
    reviewer: Mapped[str] = mapped_column(String(8))  # EXPERT | OWNER
    text: Mapped[str] = mapped_column(Text)
    excerpt: Mapped[str] = mapped_column(Text, default="")
    evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Issue(Base):
    __tablename__ = "issues"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    variant_id: Mapped[str] = mapped_column(ForeignKey("vehicle_variants.id"), index=True)
    component: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text)
    age_from: Mapped[int | None] = mapped_column(Integer)
    age_to: Mapped[int | None] = mapped_column(Integer)
    mileage_from: Mapped[int | None] = mapped_column(Integer)
    mileage_to: Mapped[int | None] = mapped_column(Integer)
    severity_hint: Mapped[str] = mapped_column(Text, default="")
    excerpt: Mapped[str] = mapped_column(Text, default="")
    area: Mapped[str] = mapped_column(String(20), default="reliability")  # reliability | used_issues
    evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ReliabilityStat(Base):
    __tablename__ = "reliability_stats"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    variant_id: Mapped[str] = mapped_column(ForeignKey("vehicle_variants.id"), index=True)
    source: Mapped[str] = mapped_column(String(120))
    metric: Mapped[str] = mapped_column(Text)
    value: Mapped[str] = mapped_column(String(80))
    year: Mapped[int | None] = mapped_column(Integer)
    excerpt: Mapped[str] = mapped_column(Text, default="")
    evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ManufacturerFact(Base):
    __tablename__ = "manufacturer_facts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    make: Mapped[str] = mapped_column(String(80), index=True)
    # HISTORY | KEY_MODEL | MARKET_POSITION | MARKET_SHARE | FINANCIAL | RELIABILITY_REPUTATION | NETWORK_ES
    # | WARRANTY | BATTERY_WARRANTY (spec 006)
    fact_type: Mapped[str] = mapped_column(String(32))
    value_num: Mapped[float | None] = mapped_column(Float)
    year: Mapped[int | None] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    positioning: Mapped[str | None] = mapped_column(String(12))  # PREMIUM | MAINSTREAM | BUDGET
    excerpt: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str] = mapped_column(Text, default="")
    source_name: Mapped[str] = mapped_column(String(200), default="")
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ValueRetention(Base):
    """Value left after N years (spec 004 FR-005): sourced, or the labelled depreciation curve."""

    __tablename__ = "value_retention"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    variant_id: Mapped[str] = mapped_column(ForeignKey("vehicle_variants.id"), index=True)
    evidence_id: Mapped[str | None] = mapped_column(ForeignKey("evidence.id"))
    years: Mapped[int] = mapped_column(SmallInteger)
    share: Mapped[float | None] = mapped_column(Numeric(4, 3))
    eur: Mapped[float | None] = mapped_column(Numeric(10, 0))
    market: Mapped[str] = mapped_column(String(4), default="ES")
    quoted_on: Mapped[date | None] = mapped_column(Date)
    basis: Mapped[str] = mapped_column(String(12))  # SOURCED | ASSUMPTION
    excerpt: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ReportRating(Base):
    __tablename__ = "report_ratings"
    message_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    chat_id: Mapped[str] = mapped_column(ForeignKey("chats.id", ondelete="CASCADE"), index=True)
    rating: Mapped[int] = mapped_column(SmallInteger)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ValueChallenge(Base):
    __tablename__ = "value_challenges"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    chat_id: Mapped[str] = mapped_column(ForeignKey("chats.id", ondelete="CASCADE"), index=True)
    turn_id: Mapped[str | None] = mapped_column(String(36))
    variant_id: Mapped[str] = mapped_column(ForeignKey("vehicle_variants.id"))
    attribute: Mapped[str | None] = mapped_column(String(40))
    claim_id: Mapped[str | None] = mapped_column(String(36))
    user_text: Mapped[str] = mapped_column(Text, default="")
    outcome: Mapped[str] = mapped_column(String(12), default="UNRESOLVED")  # CONFIRMED|CORRECTED|REMOVED|UNRESOLVED
    details: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class BrandLineup(Base):
    """Models of a make on sale in a market, with sources (spec 005 R2). Shared, refreshed after a TTL."""

    __tablename__ = "brand_lineups"
    __table_args__ = (UniqueConstraint("make", "market", name="uq_brand_lineups_make_market"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    make: Mapped[str] = mapped_column(String(80))
    market: Mapped[str] = mapped_column(String(2), default="ES")
    models: Mapped[list] = mapped_column(JSONB, default=list)  # [{model, body, powertrains, price_from_eur, ...}]
    sources: Mapped[list] = mapped_column(JSONB, default=list)  # [{url, name, type, retrieved_at}]
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ModelVersions(Base):
    """Versions sold in one generation of a model (engine, power, gearboxes, drives, years), with sources: the
    version ladder of the intake (chat 9b5c0b0c). Shared, refreshed after a TTL."""

    __tablename__ = "model_versions"
    __table_args__ = (UniqueConstraint("make", "model", "generation", "market", name="uq_model_versions"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    make: Mapped[str] = mapped_column(String(80))
    model: Mapped[str] = mapped_column(String(120))
    generation: Mapped[str] = mapped_column(String(80))
    market: Mapped[str] = mapped_column(String(2), default="ES")
    years_from: Mapped[int | None] = mapped_column(Integer)
    years_to: Mapped[int | None] = mapped_column(Integer)
    body_class: Mapped[str | None] = mapped_column(String(20))
    versions: Mapped[list] = mapped_column(JSONB, default=list)  # [{engine, fuel, engine_cc, power_kw, gearboxes, …}]
    sources: Mapped[list] = mapped_column(JSONB, default=list)  # [{url, name}]
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class IntakeEvent(Base):
    """One intake step of a chat (spec 005 R13): asked, answered, corrected, proposed, confirmed …"""

    __tablename__ = "intake_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    chat_id: Mapped[str] = mapped_column(ForeignKey("chats.id", ondelete="CASCADE"), index=True)
    turn_id: Mapped[str | None] = mapped_column(String(36))
    car_key: Mapped[str | None] = mapped_column(String(16))
    kind: Mapped[str] = mapped_column(String(20))
    item: Mapped[str | None] = mapped_column(String(16))
    details: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


# --- Deterministic computations stored per turn for reproducibility (data-model §5) -----------


class TcoEstimateRow(Base):
    __tablename__ = "tco_estimates"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    turn_id: Mapped[str] = mapped_column(String(36), index=True)
    variant_id: Mapped[str] = mapped_column(ForeignKey("vehicle_variants.id"))
    condition: Mapped[str] = mapped_column(String(8))
    age_years: Mapped[int | None] = mapped_column(Integer)
    mileage_km: Mapped[int | None] = mapped_column(Integer)
    annual_km: Mapped[int] = mapped_column(Integer)
    rates: Mapped[dict] = mapped_column(JSONB, default=dict)
    items: Mapped[list] = mapped_column(JSONB, default=list)
    annual_total: Mapped[float] = mapped_column(Float)
    five_year_total: Mapped[float] = mapped_column(Float)
    rules_version: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Simulation(Base):
    __tablename__ = "simulations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    turn_id: Mapped[str] = mapped_column(String(36), index=True)
    model_version: Mapped[str] = mapped_column(String(32))
    settings: Mapped[dict] = mapped_column(JSONB, default=dict)
    prediction: Mapped[dict | None] = mapped_column(JSONB)
    inputs: Mapped[list] = mapped_column(JSONB, default=list)
    assumptions: Mapped[list] = mapped_column(JSONB, default=list)
    results: Mapped[list] = mapped_column(JSONB, default=list)
    input_hash: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
