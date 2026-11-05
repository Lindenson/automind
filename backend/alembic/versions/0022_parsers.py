"""parser specifications, drift and the change journal (spec 011 US4, data-model "Migration 0022"): parsers,
parser_versions, parser_daily, acq_changes (one open change per object)

Revision ID: 0022
Revises: 0021
Create Date: 2026-11-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0022"
down_revision: str | Sequence[str] | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TS = sa.DateTime(timezone=True)
_STATUSES = "status IN ('draft','candidate','active','degraded','superseded','rejected','retired')"
_CHANGE_STATUSES = (
    "status IN ('proposed','replay','shadow','accepted','watch','kept','rejected','abandoned','rolled_back','reverted')"
)
_OPEN = "status IN ('proposed','replay','shadow','accepted','watch') AND closed_at IS NULL"


def upgrade() -> None:
    op.create_table(
        "parsers",
        sa.Column("reader", sa.String(40), primary_key=True),
        sa.Column("domains", postgresql.ARRAY(sa.Text()), nullable=False, server_default="{}"),
        sa.Column("page_type", sa.String(20), nullable=False, server_default="spec_table"),
        sa.Column("active_version", sa.Integer()),
        sa.Column("frozen", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", _TS, nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "parser_versions",
        sa.Column("key", sa.String(80), primary_key=True),
        sa.Column("reader", sa.String(40), sa.ForeignKey("parsers.reader", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("spec", postgresql.JSONB(), nullable=False),
        sa.Column("spec_hash", sa.String(12), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("degraded_reason", sa.Text()),
        sa.Column("zero_streak", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("author", sa.String(40), nullable=False),
        sa.Column("change_id", sa.String(36)),
        sa.Column("created_at", _TS, nullable=False, server_default=sa.func.now()),
        sa.Column("activated_at", _TS),
        sa.UniqueConstraint("reader", "version", name="uq_parser_versions_reader_version"),
        sa.CheckConstraint(_STATUSES, name="ck_parser_version_status"),
    )
    op.create_index("ix_parser_versions_status", "parser_versions", ["status"])
    op.create_table(
        "parser_daily",
        sa.Column("version_key", sa.String(80), sa.ForeignKey("parser_versions.key", ondelete="CASCADE"),
                  nullable=False),  # fmt: skip
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("pages", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fields_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fields_per_page", sa.Float(), nullable=False, server_default="0"),
        sa.Column("rows_read", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows_accepted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pass_rate", sa.Float()),
        sa.Column("zero_pages", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("structure_hash", sa.String(16)),
        sa.Column("structure_shingles", postgresql.JSONB()),
        sa.Column("structure_sim", sa.Float()),
        sa.PrimaryKeyConstraint("version_key", "day"),
    )
    op.create_table(
        "acq_changes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", _TS, nullable=False, server_default=sa.func.now()),
        sa.Column("author", sa.String(40), nullable=False),
        sa.Column("object_kind", sa.String(20), nullable=False),
        sa.Column("object_key", sa.String(160), nullable=False),
        sa.Column("from_version", sa.String(80)),
        sa.Column("to_version", sa.String(80)),
        sa.Column("diff", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("diff_hash", sa.String(12), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("evidence", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("gates", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("metrics_before", postgresql.JSONB()),
        sa.Column("metrics_after", postgresql.JSONB()),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("cost_eur", sa.Numeric(10, 4), nullable=False, server_default="0"),
        sa.Column("reverted_by", sa.String(36)),
        sa.Column("closed_at", _TS),
        sa.CheckConstraint("object_kind IN ('parser','prompt','role_model','rule','source')", name="ck_change_kind"),
        sa.CheckConstraint(_CHANGE_STATUSES, name="ck_change_status"),
    )
    op.create_index("ix_acq_changes_created_at", "acq_changes", ["created_at"])
    op.create_index("uq_acq_changes_open", "acq_changes", ["object_kind", "object_key"], unique=True,
                    postgresql_where=sa.text(_OPEN))  # fmt: skip


def downgrade() -> None:
    op.drop_index("uq_acq_changes_open", table_name="acq_changes")
    op.drop_index("ix_acq_changes_created_at", table_name="acq_changes")
    op.drop_table("acq_changes")
    op.drop_table("parser_daily")
    op.drop_index("ix_parser_versions_status", table_name="parser_versions")
    op.drop_table("parser_versions")
    op.drop_table("parsers")
