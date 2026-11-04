"""market-level facts: incentives for electrified cars (spec 006 US5, FR-016)

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-04

Purchase subsidies, the IRPF deduction, regional plans and label benefits are facts about a market, not a car.
They are researched once per market (freshness 30 days), each with dates and evidence; the status (active or
expired) is recomputed from the dates on read.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0011"
down_revision: str | Sequence[str] | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "market_facts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("market", sa.String(4), nullable=False),
        sa.Column("key", sa.String(60), nullable=False),
        sa.Column("value", JSONB(), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=True),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("evidence_ids", JSONB(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("market", "key", name="uq_market_fact"),
    )


def downgrade() -> None:
    op.drop_table("market_facts")
