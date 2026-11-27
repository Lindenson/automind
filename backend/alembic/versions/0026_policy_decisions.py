"""policy decisions (spec 015 PL3, D5): one row per pass of the dialog's policy, keyed (turn_id, pass_no), and the
policy configs by the sha256 of their canonical JSON. Additive; rows older than 90 days are deleted daily (§H D2).

Revision ID: 0026
Revises: 0025
Create Date: 2026-11-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0026"
down_revision: str | Sequence[str] | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "policy_decisions",
        sa.Column("turn_id", sa.String(36), nullable=False),
        sa.Column("pass_no", sa.SmallInteger(), nullable=False),
        sa.Column("chat_id", sa.String(36), nullable=False),
        sa.Column("case_version", sa.Integer(), nullable=False),
        sa.Column("situation", JSONB(), nullable=False),
        sa.Column("config_hash", sa.String(64), nullable=False),
        sa.Column("rules_version", sa.String(64), nullable=False),
        sa.Column("trail", JSONB(), nullable=False),
        sa.Column("decided_by", sa.String(40), nullable=False),
        sa.Column("action", JSONB(), nullable=False),
        sa.Column("next_node", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("turn_id", "pass_no"),
    )
    op.create_index("ix_policy_decisions_chat_id", "policy_decisions", ["chat_id"])
    op.create_index("ix_policy_decisions_created_at", "policy_decisions", ["created_at"])
    op.create_table(
        "policy_configs",
        sa.Column("config_hash", sa.String(64), primary_key=True),
        sa.Column("config", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("policy_configs")
    op.drop_index("ix_policy_decisions_created_at", table_name="policy_decisions")
    op.drop_index("ix_policy_decisions_chat_id", table_name="policy_decisions")
    op.drop_table("policy_decisions")
