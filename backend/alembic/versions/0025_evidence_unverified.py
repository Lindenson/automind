"""unverified evidence (spec 011 US7 T122, closes 010 T059): evidence read from a registry candidate is labelled
"unverified source" in the report and counts as half an independent source (`evidence.unverified`)

Revision ID: 0025
Revises: 0024
Create Date: 2026-11-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025"
down_revision: str | Sequence[str] | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("evidence", sa.Column("unverified", sa.Boolean(), nullable=False, server_default="false"))


def downgrade() -> None:
    op.drop_column("evidence", "unverified")
