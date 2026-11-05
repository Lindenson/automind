"""the scout (spec 011 US5 T108, closes 010 T065): learned path prefixes per capability (`capabilities.url_patterns`)
and the scout as an author of registry changes (`registry_changes.author` adds `scout`)

Revision ID: 0023
Revises: 0022
Create Date: 2026-11-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0023"
down_revision: str | Sequence[str] | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "capabilities",
        sa.Column("url_patterns", postgresql.JSONB(), nullable=False, server_default="[]"),
    )
    op.drop_constraint("ck_change_author", "registry_changes", type_="check")
    op.create_check_constraint("ck_change_author", "registry_changes", "author IN ('system','owner','scout')")


def downgrade() -> None:
    op.execute("DELETE FROM registry_changes WHERE author = 'scout'")
    op.drop_constraint("ck_change_author", "registry_changes", type_="check")
    op.create_check_constraint("ck_change_author", "registry_changes", "author IN ('system','owner')")
    op.drop_column("capabilities", "url_patterns")
