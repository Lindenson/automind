"""intake (spec 005): engine on variants, brand line-ups, intake events

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-03

- vehicle_variants: engine_cc (600–8000), power_kw (30–750), fuel (petrol|diesel|hybrid|mhev|phev|bev|lpg)
- brand_lineups (shared): models of a make on sale in a market, with sources (research R2)
- intake_events (chat-scoped, deleted with the chat): asked / answered / corrected / … (research R13)
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("vehicle_variants", sa.Column("engine_cc", sa.Integer, nullable=True))
    op.add_column("vehicle_variants", sa.Column("power_kw", sa.Integer, nullable=True))
    op.add_column("vehicle_variants", sa.Column("fuel", sa.String(8), nullable=True))
    op.create_table(
        "brand_lineups",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("make", sa.String(80), nullable=False),
        sa.Column("market", sa.String(2), nullable=False, server_default="ES"),
        sa.Column("models", postgresql.JSONB, nullable=False),
        sa.Column("sources", postgresql.JSONB, nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("make", "market", name="uq_brand_lineups_make_market"),
    )
    op.create_table(
        "intake_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("chat_id", sa.String(36), sa.ForeignKey("chats.id", ondelete="CASCADE"), nullable=False),
        sa.Column("turn_id", sa.String(36), nullable=True),
        sa.Column("car_key", sa.String(16), nullable=True),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("item", sa.String(16), nullable=True),
        sa.Column("details", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_intake_events_chat_id", "intake_events", ["chat_id"])


def downgrade() -> None:
    op.drop_index("ix_intake_events_chat_id", table_name="intake_events")
    op.drop_table("intake_events")
    op.drop_table("brand_lineups")
    op.drop_column("vehicle_variants", "fuel")
    op.drop_column("vehicle_variants", "power_kw")
    op.drop_column("vehicle_variants", "engine_cc")
