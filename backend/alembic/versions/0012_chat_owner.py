"""chat owner: an anonymous browser owner per chat (access before any external demo)

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-04

The SHA-256 of the browser's owner cookie. NULL for chats created before: the first browser that opens such a chat
claims it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | Sequence[str] | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("chats", sa.Column("owner", sa.String(64), nullable=True))
    op.create_index("ix_chats_owner", "chats", ["owner"])


def downgrade() -> None:
    op.drop_index("ix_chats_owner", table_name="chats")
    op.drop_column("chats", "owner")
