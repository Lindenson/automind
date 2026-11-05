"""source registry (spec 010 US6-US8): sources, capabilities, attempts, truth signals, change journal, runs

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016"
down_revision: str | Sequence[str] | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "sources",
        sa.Column("domain", sa.String(120), primary_key=True),
        sa.Column("source_type", sa.String(20), nullable=False),
        sa.Column("family", sa.String(120), nullable=False),
        sa.Column("markets", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("languages", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("access", sa.String(20), nullable=False, server_default="unknown"),
        sa.Column("access_evidence", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("checked_at", _TS),
        sa.Column("next_check_at", _TS),
        sa.Column("reader", sa.String(40)),
        sa.Column("frozen", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("note", sa.Text()),
        sa.Column("created_at", _TS, nullable=False),
    )
    op.create_table(
        "capabilities",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("domain", sa.String(120), nullable=False, index=True),
        sa.Column("area", sa.String(20), nullable=False),
        sa.Column("market", sa.String(8), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("priority_seed", sa.Integer()),
        sa.Column("attempts", sa.Float(), nullable=False, server_default="0"),
        sa.Column("accepted", sa.Float(), nullable=False, server_default="0"),
        sa.Column("rejected", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("right_w", sa.Float(), nullable=False, server_default="0"),
        sa.Column("wrong_w", sa.Float(), nullable=False, server_default="0"),
        sa.Column("robots_refusals", sa.Float(), nullable=False, server_default="0"),
        sa.Column("junk", sa.Float(), nullable=False, server_default="0"),
        sa.Column("cost_eur", sa.Float(), nullable=False, server_default="0"),
        sa.Column("score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("acc_mean", sa.Float(), nullable=False, server_default="0"),
        sa.Column("acc_lb", sa.Float(), nullable=False, server_default="0"),
        sa.Column("yield_", sa.Float(), nullable=False, server_default="0"),
        sa.Column("recent", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("decayed_at", _TS, nullable=False),
        sa.Column("status_since", _TS, nullable=False),
        sa.Column("last_used", _TS),
        sa.UniqueConstraint("domain", "area", "market", name="uq_capabilities"),
        sa.CheckConstraint(
            "status IN ('discovered','candidate','active','degraded','retired','blocked')", name="ck_cap_status"
        ),
    )
    op.create_index("ix_capabilities_area_status", "capabilities", ["area", "status"])
    op.create_table(
        "registry_attempts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", _TS, nullable=False, index=True),
        sa.Column("capability_id", sa.String(36), nullable=False, index=True),
        sa.Column("job_id", sa.String(36)),
        sa.Column("variant_id", sa.String(36)),
        sa.Column("url", sa.Text()),
        sa.Column("outcome", sa.String(10), nullable=False),
        sa.Column("reason", sa.String(60)),
        sa.Column("values", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_eur", sa.Float(), nullable=False, server_default="0"),
        sa.CheckConstraint(
            "outcome IN ('accepted','rejected','robots','junk','empty','error')", name="ck_attempt_outcome"
        ),
    )
    op.create_table(
        "truth_signals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", _TS, nullable=False, index=True),
        sa.Column("capability_id", sa.String(36), index=True),
        sa.Column("variant_id", sa.String(36)),
        sa.Column("attribute", sa.String(40)),
        sa.Column("claim_id", sa.String(36)),
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("verdict", sa.String(6), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.Column("blame", sa.String(10), nullable=False),
        sa.Column("details", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.CheckConstraint(
            "kind IN ('challenge','bad_source','replacement','agreement','gold')", name="ck_signal_kind"
        ),
        sa.CheckConstraint("verdict IN ('right','wrong')", name="ck_signal_verdict"),
        sa.CheckConstraint(
            "blame IN ('source','parser','extractor','relevance','check','fusion')", name="ck_signal_blame"
        ),
    )
    op.create_table(
        "registry_changes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", _TS, nullable=False, index=True),
        sa.Column("author", sa.String(8), nullable=False),
        sa.Column("capability_id", sa.String(36), index=True),
        sa.Column("domain", sa.String(120), nullable=False, index=True),
        sa.Column("change", sa.String(12), nullable=False),
        sa.Column("before", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("after", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("evidence", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("reverted_by", sa.String(36)),
        sa.Column("held", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.CheckConstraint("author IN ('system','owner')", name="ck_change_author"),
    )
    op.create_table(
        "registry_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("started_at", _TS, nullable=False),
        sa.Column("finished_at", _TS),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("changes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("discovery_queries", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_eur", sa.Numeric(10, 4), nullable=False, server_default="0"),
        sa.Column("error", sa.Text()),
    )


def downgrade() -> None:
    for t in ("registry_runs", "registry_changes", "truth_signals", "registry_attempts"):
        op.drop_table(t)
    op.drop_index("ix_capabilities_area_status", table_name="capabilities")
    op.drop_table("capabilities")
    op.drop_table("sources")
