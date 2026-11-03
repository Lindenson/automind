"""learned sources and short-lived empty search results (spec 007 US5)

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-03

Chat 757cff3d: 118 of 439 cached searches were empty and blocked new searches for a week; sources that searches
keep finding were never remembered. Empty results now expire after hours, and domains with accepted values are
kept per area and market.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | Sequence[str] | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("search_cache", sa.Column("empty", sa.Boolean(), server_default=sa.text("false"), nullable=False))
    # existing empty answers expire now, so the next research searches again
    op.execute("UPDATE search_cache SET empty = true, expires_at = least(expires_at, now()) WHERE hits = '[]'::jsonb")
    op.create_table(
        "learned_sources",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("domain", sa.String(253), nullable=False),
        sa.Column("area", sa.String(40), nullable=False),
        sa.Column("market", sa.String(8), nullable=False),
        sa.Column("source_type", sa.String(30), nullable=False),
        sa.Column("accepted_runs", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("misses", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("domain", "area", "market", name="uq_learned_source"),
    )


def downgrade() -> None:
    op.drop_table("learned_sources")
    op.drop_column("search_cache", "empty")
