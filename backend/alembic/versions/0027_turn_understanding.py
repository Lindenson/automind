"""turn understanding (spec 013 T033, understanding-spec §7): one row per turn — the input, what the model read, what
code dropped and corrected, the resolved intent and (during the S3 shadow) what the old interpreter read. Additive;
rows older than 90 days are deleted daily (owner 2026-11-27, as policy_decisions).

Revision ID: 0027
Revises: 0026
Create Date: 2026-11-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0027"
down_revision: str | Sequence[str] | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "turn_understanding",
        sa.Column("turn_id", sa.String(36), primary_key=True),
        sa.Column("chat_id", sa.String(36), nullable=False),
        sa.Column("source", sa.String(10), nullable=False),
        sa.Column("input", JSONB(), nullable=False),
        sa.Column("open_question_id", sa.String(40), nullable=True),
        sa.Column("question_repeated", sa.Boolean(), nullable=False),
        sa.Column("model", sa.String(80), nullable=True),
        sa.Column("prompt_version", sa.String(80), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("model_raw", JSONB(), nullable=True),
        sa.Column("refused", sa.Text(), nullable=True),
        sa.Column("rejected", JSONB(), nullable=False),
        sa.Column("overrides", JSONB(), nullable=False),
        sa.Column("intent", JSONB(), nullable=True),
        sa.Column("old_reading", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_turn_understanding_chat_id", "turn_understanding", ["chat_id"])
    op.create_index("ix_turn_understanding_created_at", "turn_understanding", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_turn_understanding_created_at", table_name="turn_understanding")
    op.drop_index("ix_turn_understanding_chat_id", table_name="turn_understanding")
    op.drop_table("turn_understanding")
