"""one running turn per chat (reviewer 2026-11-03)

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-03

Two tabs or a double click could start two turns over one case: the check "a turn is running" was a read
followed by an insert. The insert now takes a per-chat lock and this partial unique index makes a second
RUNNING turn of a chat impossible at the database level.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # older duplicates (if any) are closed before the index is built: the newest RUNNING turn of a chat stays
    op.execute(
        """
        UPDATE turns t SET status = 'FAILED', finished_at = now()
        WHERE t.status = 'RUNNING' AND EXISTS (
            SELECT 1 FROM turns n WHERE n.chat_id = t.chat_id AND n.status = 'RUNNING' AND n.seq > t.seq)
        """
    )
    op.create_index(
        "uq_turns_one_running_per_chat", "turns", ["chat_id"], unique=True, postgresql_where="status = 'RUNNING'"
    )


def downgrade() -> None:
    op.drop_index("uq_turns_one_running_per_chat", table_name="turns")
