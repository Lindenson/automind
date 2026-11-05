"""insight (spec 010 US3-US5): issues grouped from failures, and the analysis runs

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015"
down_revision: str | Sequence[str] | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "insight_issues",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("fingerprint", sa.String(64), nullable=False, unique=True),
        sa.Column("component", sa.String(16), nullable=False),
        sa.Column("klass", sa.String(40), nullable=False),
        sa.Column("key", sa.String(200), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("count_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("count_7d", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("chats_7d", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("impact", sa.Float(), nullable=False, server_default="0"),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("examples", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("diagnosis", postgresql.JSONB()),
        sa.Column("diagnosed_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
        sa.Column("status_history", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("fixed_at", sa.DateTime(timezone=True)),
        sa.Column("fixed_ref", sa.String(80)),
        sa.Column("source", sa.String(16), nullable=False, server_default="auto"),
        sa.CheckConstraint(
            "status IN ('open','acknowledged','fixed','wontfix','regression')", name="ck_insight_issues_status"
        ),
    )
    op.create_index("ix_insight_issues_status_impact", "insight_issues", ["status", "impact"])
    op.create_table(
        "insight_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("groups", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("issues_new", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("diagnosed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_eur", sa.Numeric(10, 4), nullable=False, server_default="0"),
        sa.Column("error", sa.Text()),
    )


def downgrade() -> None:
    op.drop_table("insight_runs")
    op.drop_index("ix_insight_issues_status_impact", table_name="insight_issues")
    op.drop_table("insight_issues")
