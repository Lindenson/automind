"""model versions: the versions sold in each generation of a model (the intake's version ladder)

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013"
down_revision: str | Sequence[str] | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "model_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("make", sa.String(80), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("generation", sa.String(80), nullable=False),
        sa.Column("market", sa.String(2), nullable=False),
        sa.Column("years_from", sa.Integer()),
        sa.Column("years_to", sa.Integer()),
        sa.Column("body_class", sa.String(20)),
        sa.Column("versions", postgresql.JSONB(), nullable=False),
        sa.Column("sources", postgresql.JSONB(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("make", "model", "generation", "market", name="uq_model_versions"),
    )


def downgrade() -> None:
    op.drop_table("model_versions")
