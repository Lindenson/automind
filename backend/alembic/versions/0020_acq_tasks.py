"""worker task queue (spec 011 US2): acq_tasks (Postgres SKIP LOCKED queue) and acq_workers (heartbeats)

Revision ID: 0020
Revises: 0017
Create Date: 2026-11-05

NOTE: written on the US2 branch in parallel with 0018/0019 (US1); rechain `down_revision` to "0019" at merge.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0020"
down_revision: str | Sequence[str] | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "acq_tasks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("dedupe_key", sa.String(200), nullable=False, unique=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("priority", sa.SmallInteger(), nullable=False, server_default="5"),
        sa.Column("state", sa.String(10), nullable=False, server_default="queued"),
        sa.Column("run_at", _TS, nullable=False, server_default=sa.func.now()),
        sa.Column("attempts", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.SmallInteger(), nullable=False, server_default="3"),
        sa.Column("lease_until", _TS),
        sa.Column("locked_by", sa.String(80)),
        sa.Column("last_error", sa.Text()),
        sa.Column("result", postgresql.JSONB()),
        sa.Column("cost_eur", sa.Numeric(10, 4), nullable=False, server_default="0"),
        sa.Column("created_at", _TS, nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", _TS),
        sa.Column("finished_at", _TS),
    )
    op.create_index("ix_acq_tasks_due", "acq_tasks", ["state", "priority", "run_at"])
    op.create_index("ix_acq_tasks_finished_at", "acq_tasks", ["finished_at"])
    op.create_table(
        "acq_workers",
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("host", sa.String(120), nullable=False),
        sa.Column("pid", sa.Integer(), nullable=False),
        sa.Column("version", sa.String(80), nullable=False),
        sa.Column("started_at", _TS, nullable=False),
        sa.Column("beat_at", _TS, nullable=False),
        sa.Column("tasks_done", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_table("acq_workers")
    op.drop_index("ix_acq_tasks_finished_at", table_name="acq_tasks")
    op.drop_index("ix_acq_tasks_due", table_name="acq_tasks")
    op.drop_table("acq_tasks")
