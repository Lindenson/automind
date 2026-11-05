"""gold values (spec 011 US1, data-model "Migration 0019"): open datasets, gold values per variant and attribute,
and the cache of extractor outputs for replay

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0019"
down_revision: str | Sequence[str] | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "gold_datasets",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("version", sa.String(80)),
        sa.Column("licence", sa.String(30), nullable=False),
        sa.Column("url", sa.Text()),
        sa.Column("rows_read", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows_matched", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("loaded_at", _TS),
        sa.Column("next_refresh_at", _TS),
        sa.Column("error", sa.Text()),
    )
    op.create_table(
        "gold_values",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "variant_id", sa.String(36), sa.ForeignKey("vehicle_variants.id", ondelete="CASCADE"), nullable=False,
            index=True,
        ),  # fmt: skip
        sa.Column("attribute", sa.String(40), nullable=False),
        sa.Column("value_num", sa.Float()),
        sa.Column("value_text", sa.Text()),
        sa.Column("unit", sa.String(20), nullable=False),
        sa.Column("tolerance", sa.Float(), nullable=False),
        sa.Column("tolerance_kind", sa.String(4), nullable=False),
        sa.Column("origin", sa.String(16), nullable=False),
        sa.Column("dataset_id", sa.String(40), sa.ForeignKey("gold_datasets.id")),
        sa.Column("record_key", sa.Text()),
        sa.Column("match_rule", sa.String(80), nullable=False),
        sa.Column("confidence", sa.String(8), nullable=False),
        sa.Column("registrations", sa.Integer()),
        sa.Column("verified_at", _TS, nullable=False),
        sa.Column("flagged", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("flag_reason", sa.Text()),
        sa.Column("details", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.UniqueConstraint("variant_id", "attribute", "origin", "dataset_id", name="uq_gold_values"),
    )
    op.create_table(
        "extraction_cache",
        sa.Column("prompt_hash", sa.String(12), nullable=False),
        sa.Column("model", sa.String(80), nullable=False),
        sa.Column("blob_sha256", sa.String(64), nullable=False),
        sa.Column("area", sa.String(20), nullable=False),
        sa.Column("output", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", _TS, nullable=False, index=True),
        sa.PrimaryKeyConstraint("prompt_hash", "model", "blob_sha256", "area"),
    )


def downgrade() -> None:
    op.drop_table("extraction_cache")
    op.drop_table("gold_values")
    op.drop_table("gold_datasets")
