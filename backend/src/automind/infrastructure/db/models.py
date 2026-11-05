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
    LargeBinary,
    Numeric,
    PrimaryKeyConstraint,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
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
    # spec 011 FR-002: who produced the value — reader | extractor | dataset | user, its version and model
    producer: Mapped[str] = mapped_column(String(12), default="extractor", server_default="extractor")
    producer_version: Mapped[str | None] = mapped_column(String(80))  # km77@v1 | extract_specs@v2 | legacy
    model: Mapped[str | None] = mapped_column(String(80))  # served model of extractor claims
    snapshot_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("page_snapshots.id", ondelete="SET NULL"), index=True
    )


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
    # spec 010 FR-022: when the area last tried the registry's sources with the escalation to the other European
    # markets (None: never; an area below its minimum then gets that round in the first research of a turn)
    registry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stage_versions: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")  # spec 011 R2


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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    # spec 010 FR-004: the configured model, whether a fallback answered, and which prompt version was used
    primary_model: Mapped[str | None] = mapped_column(String(80))
    fallback: Mapped[bool] = mapped_column(Boolean, default=False)
    prompt_name: Mapped[str | None] = mapped_column(String(40))
    prompt_version: Mapped[str | None] = mapped_column(String(12))
    prompt_hash: Mapped[str | None] = mapped_column(String(12))


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
    prompt_version: Mapped[str | None] = mapped_column(String(80))  # spec 011: method LLM only
    model: Mapped[str | None] = mapped_column(String(80))


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


# --- Spec 010: observation, insight, source registry -------------------------------------------


class TurnOutcome(Base):
    """One per turn: what was asked, what happened, failure classes, signals and a 0-1 score (US1)."""

    __tablename__ = "turn_outcomes"
    turn_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    chat_id: Mapped[str] = mapped_column(String(36), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    request_kind: Mapped[str | None] = mapped_column(String(24))
    action: Mapped[str | None] = mapped_column(String(24))
    language: Mapped[str | None] = mapped_column(String(8))
    persona: Mapped[str | None] = mapped_column(String(16))
    path: Mapped[list] = mapped_column(JSONB, default=list)
    status: Mapped[str] = mapped_column(String(24))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    cost_eur: Mapped[float] = mapped_column(Numeric(10, 4), default=0)
    relation_next: Mapped[str | None] = mapped_column(String(16))
    failure_classes: Mapped[list] = mapped_column(JSONB, default=list)
    signals: Mapped[dict] = mapped_column(JSONB, default=dict)
    score: Mapped[float] = mapped_column(Float)
    settings_version: Mapped[str | None] = mapped_column(String(16))


FEEDBACK_KINDS = ("rating", "wrong_value", "bad_source", "complaint", "rephrase", "correction")


class Feedback(Base):
    """Every user signal in one place (US2)."""

    __tablename__ = "feedback"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    chat_id: Mapped[str] = mapped_column(String(36), index=True)
    turn_id: Mapped[str | None] = mapped_column(String(36), index=True)
    message_id: Mapped[str | None] = mapped_column(String(36))
    kind: Mapped[str] = mapped_column(String(16))
    rating: Mapped[int | None] = mapped_column(SmallInteger)
    variant_id: Mapped[str | None] = mapped_column(String(36))
    attribute: Mapped[str | None] = mapped_column(String(40))
    area: Mapped[str | None] = mapped_column(String(20))
    domain: Mapped[str | None] = mapped_column(String(120))
    url: Mapped[str | None] = mapped_column(Text)
    claim_id: Mapped[str | None] = mapped_column(String(36))
    text: Mapped[str | None] = mapped_column(String(1000))
    outcome: Mapped[str | None] = mapped_column(String(16))


class InsightIssue(Base):
    """A group of failures with a diagnosis and a proposed fix; never applied by the system (US3)."""

    __tablename__ = "insight_issues"
    __table_args__ = (Index("ix_insight_issues_status_impact", "status", "impact"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True)
    component: Mapped[str] = mapped_column(String(16))
    klass: Mapped[str] = mapped_column(String(40))
    key: Mapped[str] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(String(200))
    count_total: Mapped[int] = mapped_column(Integer, default=0)
    count_7d: Mapped[int] = mapped_column(Integer, default=0)
    chats_7d: Mapped[int] = mapped_column(Integer, default=0)
    impact: Mapped[float] = mapped_column(Float, default=0.0)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    examples: Mapped[list] = mapped_column(JSONB, default=list)
    diagnosis: Mapped[dict | None] = mapped_column(JSONB)
    diagnosed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="open")
    status_history: Mapped[list] = mapped_column(JSONB, default=list)
    fixed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fixed_ref: Mapped[str | None] = mapped_column(String(80))
    source: Mapped[str] = mapped_column(String(16), default="auto")


class InsightRun(Base):
    __tablename__ = "insight_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    kind: Mapped[str] = mapped_column(String(8))
    groups: Mapped[int] = mapped_column(Integer, default=0)
    issues_new: Mapped[int] = mapped_column(Integer, default=0)
    diagnosed: Mapped[int] = mapped_column(Integer, default=0)
    cost_eur: Mapped[float] = mapped_column(Numeric(10, 4), default=0)
    error: Mapped[str | None] = mapped_column(Text)


class SourceRow(Base):
    __tablename__ = "sources"
    domain: Mapped[str] = mapped_column(String(120), primary_key=True)
    source_type: Mapped[str] = mapped_column(String(20))
    family: Mapped[str] = mapped_column(String(120))
    markets: Mapped[list] = mapped_column(JSONB, default=list)
    languages: Mapped[list] = mapped_column(JSONB, default=list)
    access: Mapped[str] = mapped_column(String(20), default="unknown")
    access_evidence: Mapped[dict] = mapped_column(JSONB, default=dict)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reader: Mapped[str | None] = mapped_column(String(40))
    frozen: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class CapabilityRow(Base):
    __tablename__ = "capabilities"
    __table_args__ = (
        UniqueConstraint("domain", "area", "market", name="uq_capabilities"),
        Index("ix_capabilities_area_status", "area", "status"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    domain: Mapped[str] = mapped_column(String(120), index=True)
    area: Mapped[str] = mapped_column(String(20))
    market: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(12))
    priority_seed: Mapped[int | None] = mapped_column(Integer)
    attempts: Mapped[float] = mapped_column(Float, default=0.0)
    accepted: Mapped[float] = mapped_column(Float, default=0.0)
    rejected: Mapped[dict] = mapped_column(JSONB, default=dict)
    right_w: Mapped[float] = mapped_column(Float, default=0.0)
    wrong_w: Mapped[float] = mapped_column(Float, default=0.0)
    robots_refusals: Mapped[float] = mapped_column(Float, default=0.0)
    junk: Mapped[float] = mapped_column(Float, default=0.0)
    cost_eur: Mapped[float] = mapped_column(Float, default=0.0)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    acc_mean: Mapped[float] = mapped_column(Float, default=0.0)
    acc_lb: Mapped[float] = mapped_column(Float, default=0.0)
    yield_: Mapped[float] = mapped_column("yield_", Float, default=0.0)
    recent: Mapped[list] = mapped_column(JSONB, default=list)  # last outcomes (accepted: bool), newest last
    decayed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    status_since: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    last_used: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # spec 011 US3 (0021): decayed weight of accuracy signals (promotion minimum), family agreements, today's
    # exploration spend (reset by the daily roll-up)
    signals_w: Mapped[float] = mapped_column(Float, default=0.0)
    families_agree: Mapped[float] = mapped_column(Float, default=0.0)
    explore_spent_eur: Mapped[float] = mapped_column(Float, default=0.0)
    # spec 011 US5 (0023): path prefixes of pages that gave accepted values (the scout's locator), e.g. ["/fichas/"];
    # the registry's `site:` queries then name `domain/prefix`
    url_patterns: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")


class RegistryAttempt(Base):
    __tablename__ = "registry_attempts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    capability_id: Mapped[str] = mapped_column(String(36), index=True)
    job_id: Mapped[str | None] = mapped_column(String(36))
    variant_id: Mapped[str | None] = mapped_column(String(36))
    url: Mapped[str | None] = mapped_column(Text)
    outcome: Mapped[str] = mapped_column(String(10))
    reason: Mapped[str | None] = mapped_column(String(60))
    values: Mapped[int] = mapped_column(Integer, default=0)
    cost_eur: Mapped[float] = mapped_column(Float, default=0.0)
    # spec 011 FR-002: versions of the producer and the pipeline stages, the page snapshot, searches spent
    producer_version: Mapped[str | None] = mapped_column(String(80))
    model: Mapped[str | None] = mapped_column(String(80))
    snapshot_id: Mapped[str | None] = mapped_column(String(36))
    stage_versions: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    searches: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class TruthSignal(Base):
    __tablename__ = "truth_signals"
    __table_args__ = (Index("ix_truth_signals_claim_kind", "claim_id", "kind"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    capability_id: Mapped[str | None] = mapped_column(String(36), index=True)
    variant_id: Mapped[str | None] = mapped_column(String(36))
    attribute: Mapped[str | None] = mapped_column(String(40))
    claim_id: Mapped[str | None] = mapped_column(String(36))
    kind: Mapped[str] = mapped_column(String(12))
    verdict: Mapped[str] = mapped_column(String(6))
    weight: Mapped[float] = mapped_column(Float)
    blame: Mapped[str] = mapped_column(String(10))  # the top component under the 010 labels
    details: Mapped[dict] = mapped_column(JSONB, default=dict)
    # spec 011 US3 (0021): vector blame (research R9), the gold value and page behind the signal, judge pending
    blame_vector: Mapped[dict | None] = mapped_column(JSONB)
    component: Mapped[str | None] = mapped_column(String(160))  # parser:km77@v1 | source:<domain> | ...
    gold_id: Mapped[str | None] = mapped_column(String(36))
    snapshot_id: Mapped[str | None] = mapped_column(String(36))
    disputed: Mapped[bool] = mapped_column(Boolean, default=False)


class RegistryChange(Base):
    __tablename__ = "registry_changes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    author: Mapped[str] = mapped_column(String(8))
    capability_id: Mapped[str | None] = mapped_column(String(36), index=True)
    domain: Mapped[str] = mapped_column(String(120), index=True)
    change: Mapped[str] = mapped_column(String(12))
    before: Mapped[dict] = mapped_column(JSONB, default=dict)
    after: Mapped[dict] = mapped_column(JSONB, default=dict)
    reason: Mapped[str] = mapped_column(Text)
    evidence: Mapped[dict] = mapped_column(JSONB, default=dict)
    reverted_by: Mapped[str | None] = mapped_column(String(36))
    held: Mapped[bool] = mapped_column(Boolean, default=False)


class RegistryRun(Base):
    __tablename__ = "registry_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    kind: Mapped[str] = mapped_column(String(8))
    changes: Mapped[int] = mapped_column(Integer, default=0)
    discovery_queries: Mapped[int] = mapped_column(Integer, default=0)
    cost_eur: Mapped[float] = mapped_column(Numeric(10, 4), default=0)
    error: Mapped[str | None] = mapped_column(Text)


# --- spec 011: acquisition engine ---------------------------------------------------------------------------------


class SnapshotBlob(Base):
    """A raw page body, zstd-compressed, content-addressed by the sha256 of the raw bytes (research R1)."""

    __tablename__ = "snapshot_blobs"
    sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    codec: Mapped[str] = mapped_column(String(8))
    body: Mapped[bytes] = mapped_column(LargeBinary)
    raw_bytes: Mapped[int] = mapped_column(Integer)
    stored_bytes: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class PageSnapshot(Base):
    """One network fetch of a page (never a cache hit); replayable when its raw body is kept."""

    __tablename__ = "page_snapshots"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    url: Mapped[str] = mapped_column(Text)
    url_hash: Mapped[str] = mapped_column(String(64), index=True)
    final_url: Mapped[str | None] = mapped_column(Text)
    domain: Mapped[str] = mapped_column(String(200), index=True)
    document_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("documents.id", ondelete="SET NULL"), index=True
    )
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    blob_sha256: Mapped[str | None] = mapped_column(String(64), ForeignKey("snapshot_blobs.sha256"), index=True)
    content_type: Mapped[str | None] = mapped_column(String(60))
    http_status: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16))  # OK | NO_CONTENT | REFUSED | ERROR
    replayable: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    retention_class: Mapped[str] = mapped_column(String(10), default="plain", server_default="plain")
    keep_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    accepted_values: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    variant_ids: Mapped[list[str]] = mapped_column(ARRAY(String(36)), default=list, server_default="{}")
    structure_hash: Mapped[str | None] = mapped_column(String(16))
    parser_version: Mapped[str | None] = mapped_column(String(80))


class GoldDataset(Base):
    __tablename__ = "gold_datasets"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)  # eea_co2_2024, rdw, reference_set, challenges
    name: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(20))  # eea_co2 | eea_obfcm | rdw | kba | reference_set | challenge
    version: Mapped[str | None] = mapped_column(String(80))
    licence: Mapped[str] = mapped_column(String(30))
    url: Mapped[str | None] = mapped_column(Text)
    rows_read: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    rows_matched: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    loaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_refresh_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)


class GoldValueRow(Base):
    """A reference value of one variant's attribute, with its origin, matching rule and tolerance (FR-003)."""

    __tablename__ = "gold_values"
    __table_args__ = (UniqueConstraint("variant_id", "attribute", "origin", "dataset_id", name="uq_gold_values"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    variant_id: Mapped[str] = mapped_column(ForeignKey("vehicle_variants.id", ondelete="CASCADE"), index=True)
    attribute: Mapped[str] = mapped_column(String(40))
    value_num: Mapped[float | None] = mapped_column(Float)
    value_text: Mapped[str | None] = mapped_column(Text)
    unit: Mapped[str] = mapped_column(String(20))
    tolerance: Mapped[float] = mapped_column(Float)
    tolerance_kind: Mapped[str] = mapped_column(String(4))  # abs | rel
    origin: Mapped[str] = mapped_column(String(16))  # dataset | challenge | reference_set
    dataset_id: Mapped[str | None] = mapped_column(String(40), ForeignKey("gold_datasets.id"))
    record_key: Mapped[str | None] = mapped_column(Text)
    match_rule: Mapped[str] = mapped_column(String(80))
    confidence: Mapped[str] = mapped_column(String(8))  # HIGH | MEDIUM
    registrations: Mapped[int | None] = mapped_column(Integer)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    flagged: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    flag_reason: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")


class ExtractionCache(Base):
    """Extractor outputs per (prompt, model, page body, area): a second replay of a version costs nothing (R4)."""

    __tablename__ = "extraction_cache"
    __table_args__ = (PrimaryKeyConstraint("prompt_hash", "model", "blob_sha256", "area"),)
    prompt_hash: Mapped[str] = mapped_column(String(12))
    model: Mapped[str] = mapped_column(String(80))
    blob_sha256: Mapped[str] = mapped_column(String(64))
    area: Mapped[str] = mapped_column(String(20))
    output: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


# --- spec 011 US2: the worker's task queue (migration 0020, contracts/task-queue.md) ---------------------------------


class AcqTask(Base):
    """One unit of background work; claimed with FOR UPDATE SKIP LOCKED (acquisition/worker/queue.py)."""

    __tablename__ = "acq_tasks"
    __table_args__ = (Index("ix_acq_tasks_due", "state", "priority", "run_at"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    kind: Mapped[str] = mapped_column(String(40))
    dedupe_key: Mapped[str] = mapped_column(String(200), unique=True)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    priority: Mapped[int] = mapped_column(SmallInteger, default=5)
    state: Mapped[str] = mapped_column(String(10), default="queued")  # queued, running, done, failed, dead
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    attempts: Mapped[int] = mapped_column(SmallInteger, default=0)
    max_attempts: Mapped[int] = mapped_column(SmallInteger, default=3)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[str | None] = mapped_column(String(80))
    last_error: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict | None] = mapped_column(JSONB)
    cost_eur: Mapped[float] = mapped_column(Numeric(10, 4), default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class AcqWorker(Base):
    __tablename__ = "acq_workers"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    host: Mapped[str] = mapped_column(String(120))
    pid: Mapped[int] = mapped_column(Integer)
    version: Mapped[str] = mapped_column(String(80))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    beat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    tasks_done: Mapped[int] = mapped_column(Integer, default=0)


# --- spec 011 US3: honest reputation (migration 0021) ----------------------------------------------------------------


class ComponentReputation(Base):
    """Decayed right/wrong weight of a pipeline component that vector blame can name (research R9)."""

    __tablename__ = "component_reputation"
    __table_args__ = (PrimaryKeyConstraint("kind", "key"),)
    kind: Mapped[str] = mapped_column(String(12))  # parser | extractor | relevance | rule | fusion
    key: Mapped[str] = mapped_column(String(160))  # km77@v1 | extract_specs@v3|<model> | sense.<rule> | merge@1
    right_w: Mapped[float] = mapped_column(Float, default=0.0)
    wrong_w: Mapped[float] = mapped_column(Float, default=0.0)
    acc_lb: Mapped[float] = mapped_column(Float, default=0.0)
    decayed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AcqDaily(Base):
    """Daily roll-up per area and market: searches per accepted value (SC-009) and the accuracy KPI."""

    __tablename__ = "acq_daily"
    __table_args__ = (PrimaryKeyConstraint("day", "area", "market"),)
    day: Mapped[date] = mapped_column(Date)
    area: Mapped[str] = mapped_column(String(20))
    market: Mapped[str] = mapped_column(String(8))
    searches: Mapped[int] = mapped_column(Integer, default=0)
    pages: Mapped[int] = mapped_column(Integer, default=0)
    accepted_values: Mapped[int] = mapped_column(Integer, default=0)
    wrong_values: Mapped[int] = mapped_column(Integer, default=0)
    gold_checked: Mapped[int] = mapped_column(Integer, default=0)
    gold_wrong: Mapped[int] = mapped_column(Integer, default=0)
    cost_eur: Mapped[float] = mapped_column(Numeric(10, 4), default=0)
    explore_eur: Mapped[float] = mapped_column(Numeric(10, 4), default=0)


class KpiBaseline(Base):
    """A recorded window of the accuracy and satisfaction KPIs (FR-014), e.g. "pre-autonomy"."""

    __tablename__ = "kpi_baselines"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(60), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    values: Mapped[dict] = mapped_column(JSONB, default=dict)
    recorded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(Text)


# --- spec 011 US4: parser specifications, drift and the change journal (migration 0022) ----------------------------

OPEN_CHANGE_STATUSES = ("proposed", "replay", "shadow", "accepted", "watch")


class Parser(Base):
    """A site reader whose versions are declarative specs (contracts/parser-spec.md)."""

    __tablename__ = "parsers"
    reader: Mapped[str] = mapped_column(String(40), primary_key=True)  # km77
    domains: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    page_type: Mapped[str] = mapped_column(String(20), default="spec_table")
    active_version: Mapped[int | None] = mapped_column(Integer)
    frozen: Mapped[bool] = mapped_column(Boolean, default=False)  # the owner's freeze: no automatic change
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ParserVersion(Base):
    """One version of a parser spec, `km77@v1`; the live registry runs the active (or degraded) one per reader."""

    __tablename__ = "parser_versions"
    __table_args__ = (UniqueConstraint("reader", "version", name="uq_parser_versions_reader_version"),)
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    reader: Mapped[str] = mapped_column(String(40), ForeignKey("parsers.reader", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer)
    spec: Mapped[dict] = mapped_column(JSONB)
    spec_hash: Mapped[str] = mapped_column(String(12))
    # draft | candidate | active | degraded | superseded | rejected | retired
    status: Mapped[str] = mapped_column(String(12), index=True)
    degraded_reason: Mapped[str | None] = mapped_column(Text)
    zero_streak: Mapped[int] = mapped_column(Integer, default=0)
    author: Mapped[str] = mapped_column(String(40))  # seed | owner | agent:parser_doctor
    change_id: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ParserDaily(Base):
    """Daily metrics of a parser version (research R12): yield, pass rate, structure fingerprint."""

    __tablename__ = "parser_daily"
    __table_args__ = (PrimaryKeyConstraint("version_key", "day"),)
    version_key: Mapped[str] = mapped_column(String(80), ForeignKey("parser_versions.key", ondelete="CASCADE"))
    day: Mapped[date] = mapped_column(Date)
    pages: Mapped[int] = mapped_column(Integer, default=0)
    fields_total: Mapped[int] = mapped_column(Integer, default=0)
    fields_per_page: Mapped[float] = mapped_column(Float, default=0.0)
    rows_read: Mapped[int] = mapped_column(Integer, default=0)
    rows_accepted: Mapped[int] = mapped_column(Integer, default=0)
    pass_rate: Mapped[float | None] = mapped_column(Float)
    zero_pages: Mapped[int] = mapped_column(Integer, default=0)
    structure_hash: Mapped[str | None] = mapped_column(String(16))
    structure_shingles: Mapped[list | None] = mapped_column(JSONB)
    structure_sim: Mapped[float | None] = mapped_column(Float)


class AcqChange(Base):
    """The journal of gated declarative changes and of automatic status changes (research R15)."""

    __tablename__ = "acq_changes"
    __table_args__ = (
        # one open change per object (FR-018); a closed row (closed_at set) never blocks the next one
        Index("uq_acq_changes_open", "object_kind", "object_key", unique=True, postgresql_where=text(
            "status IN ('proposed','replay','shadow','accepted','watch') AND closed_at IS NULL")),
    )  # fmt: skip
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    author: Mapped[str] = mapped_column(String(40))  # agent:parser_doctor | system | owner | …
    object_kind: Mapped[str] = mapped_column(String(20))  # parser | prompt | role_model | rule | source
    object_key: Mapped[str] = mapped_column(String(160))
    from_version: Mapped[str | None] = mapped_column(String(80))
    to_version: Mapped[str | None] = mapped_column(String(80))
    diff: Mapped[dict] = mapped_column(JSONB, default=dict)
    diff_hash: Mapped[str] = mapped_column(String(12))
    reason: Mapped[str] = mapped_column(Text)
    evidence: Mapped[dict] = mapped_column(JSONB, default=dict)
    gates: Mapped[dict] = mapped_column(JSONB, default=dict)
    metrics_before: Mapped[dict | None] = mapped_column(JSONB)
    metrics_after: Mapped[dict | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(12))
    explanation: Mapped[str] = mapped_column(Text)
    cost_eur: Mapped[float] = mapped_column(Numeric(10, 4), default=0)
    reverted_by: Mapped[str | None] = mapped_column(String(36))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
