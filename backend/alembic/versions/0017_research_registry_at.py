"""research_runs.registry_at: when an area's research last tried the registry's sources with the escalation to the
other European markets (spec 010 FR-022: "no data" only after the registry's sources were tried)

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | Sequence[str] | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("research_runs", sa.Column("registry_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("research_runs", "registry_at")
