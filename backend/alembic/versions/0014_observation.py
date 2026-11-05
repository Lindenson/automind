"""observation (spec 010 US1, US2): turn outcomes, one feedback table, prompt identity and fallback per model call

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014"
down_revision: str | Sequence[str] | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("llm_calls", sa.Column("primary_model", sa.String(80)))
    op.add_column("llm_calls", sa.Column("fallback", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("llm_calls", sa.Column("prompt_name", sa.String(40)))
    op.add_column("llm_calls", sa.Column("prompt_version", sa.String(12)))
    op.add_column("llm_calls", sa.Column("prompt_hash", sa.String(12)))
    op.create_index("ix_llm_calls_created_at", "llm_calls", ["created_at"])
    op.create_table(
        "turn_outcomes",
        sa.Column("turn_id", sa.String(36), primary_key=True),
        sa.Column("chat_id", sa.String(36), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_kind", sa.String(24)),
        sa.Column("action", sa.String(24)),
        sa.Column("language", sa.String(8)),
        sa.Column("persona", sa.String(16)),
        sa.Column("path", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("duration_ms", sa.Integer()),
        sa.Column("cost_eur", sa.Numeric(10, 4), nullable=False, server_default="0"),
        sa.Column("relation_next", sa.String(16)),
        sa.Column("failure_classes", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("signals", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("settings_version", sa.String(16)),
    )
    op.create_table(
        "feedback",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("chat_id", sa.String(36), nullable=False, index=True),
        sa.Column("turn_id", sa.String(36), index=True),
        sa.Column("message_id", sa.String(36)),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("rating", sa.SmallInteger()),
        sa.Column("variant_id", sa.String(36)),
        sa.Column("attribute", sa.String(40)),
        sa.Column("area", sa.String(20)),
        sa.Column("domain", sa.String(120)),
        sa.Column("url", sa.Text()),
        sa.Column("claim_id", sa.String(36)),
        sa.Column("text", sa.String(1000)),
        sa.Column("outcome", sa.String(16)),
        sa.CheckConstraint(
            "kind IN ('rating','wrong_value','bad_source','complaint','rephrase','correction')", name="ck_feedback_kind"
        ),
    )


def downgrade() -> None:
    op.drop_table("feedback")
    op.drop_table("turn_outcomes")
    op.drop_index("ix_llm_calls_created_at", table_name="llm_calls")
    for c in ("prompt_hash", "prompt_version", "prompt_name", "fallback", "primary_model"):
        op.drop_column("llm_calls", c)
