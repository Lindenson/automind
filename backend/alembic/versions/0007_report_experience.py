"""report experience (spec 004): gearbox/drive/trim on variants, value retention, ratings, value challenges

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-03

- vehicle_variants: transmission, drive (FR-028), trim, trim_level, price_eur (FR-029, equal level)
- manufacturer_facts: wider fact_type (MARKET_SHARE, FINANCIAL, RELIABILITY_REPUTATION, NETWORK_ES), value_num, year
- value_retention (shared), report_ratings and value_challenges (chat-scoped, deleted with the chat)
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("vehicle_variants", sa.Column("transmission", sa.String(16), nullable=True))
    op.add_column("vehicle_variants", sa.Column("drive", sa.String(4), nullable=True))
    op.add_column("vehicle_variants", sa.Column("trim", sa.String(64), nullable=True))
    op.add_column("vehicle_variants", sa.Column("trim_level", sa.String(4), nullable=True))
    op.add_column("vehicle_variants", sa.Column("price_eur", sa.Numeric(10, 0), nullable=True))
    op.alter_column("manufacturer_facts", "fact_type", type_=sa.String(32), existing_type=sa.String(16))
    op.add_column("manufacturer_facts", sa.Column("value_num", sa.Float, nullable=True))
    op.add_column("manufacturer_facts", sa.Column("year", sa.Integer, nullable=True))
    op.create_table(
        "value_retention",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("variant_id", sa.String(36), sa.ForeignKey("vehicle_variants.id"), nullable=False, index=True),
        sa.Column("evidence_id", sa.String(36), sa.ForeignKey("evidence.id"), nullable=True),
        sa.Column("years", sa.SmallInteger, nullable=False),
        sa.Column("share", sa.Numeric(4, 3), nullable=True),
        sa.Column("eur", sa.Numeric(10, 0), nullable=True),
        sa.Column("market", sa.String(4), nullable=False, server_default="ES"),
        sa.Column("quoted_on", sa.Date, nullable=True),
        sa.Column("basis", sa.String(12), nullable=False),
        sa.Column("excerpt", sa.Text, nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "report_ratings",
        sa.Column("message_id", sa.String(36), primary_key=True),
        sa.Column("chat_id", sa.String(36), sa.ForeignKey("chats.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("rating", sa.SmallInteger, nullable=False),
        sa.Column("note", sa.Text, nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("rating BETWEEN 1 AND 5", name="ck_report_ratings_rating"),
    )
    op.create_table(
        "value_challenges",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("chat_id", sa.String(36), sa.ForeignKey("chats.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("turn_id", sa.String(36), nullable=True),
        sa.Column("variant_id", sa.String(36), sa.ForeignKey("vehicle_variants.id"), nullable=False),
        sa.Column("attribute", sa.String(40), nullable=True),
        sa.Column("claim_id", sa.String(36), nullable=True),
        sa.Column("user_text", sa.Text, nullable=False, server_default=""),
        sa.Column("outcome", sa.String(12), nullable=False, server_default="UNRESOLVED"),
        sa.Column("details", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("value_challenges")
    op.drop_table("report_ratings")
    op.drop_table("value_retention")
    op.drop_column("manufacturer_facts", "year")
    op.drop_column("manufacturer_facts", "value_num")
    op.alter_column("manufacturer_facts", "fact_type", type_=sa.String(16), existing_type=sa.String(32))
    for col in ("price_eur", "trim_level", "trim", "drive", "transmission"):
        op.drop_column("vehicle_variants", col)
