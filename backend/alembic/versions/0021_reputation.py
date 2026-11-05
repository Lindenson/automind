"""honest reputation (spec 011 US3, data-model "Migration 0021"): accuracy-signal weight and exploration spend on
capabilities, vector blame on truth signals (+ kind `physics`), component reputation, daily roll-up, KPI baselines

Revision ID: 0021
Revises: 0020
Create Date: 2026-11-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0021"
down_revision: str | Sequence[str] | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TS = sa.DateTime(timezone=True)
_KINDS_010 = "kind IN ('challenge','bad_source','replacement','agreement','gold')"
_KINDS_011 = "kind IN ('challenge','bad_source','replacement','agreement','gold','physics')"


def upgrade() -> None:
    for col in ("signals_w", "families_agree", "explore_spent_eur"):
        op.add_column("capabilities", sa.Column(col, sa.Float(), nullable=False, server_default="0"))
    # the signals already recorded (challenges, bad sources) are accuracy evidence: they count towards promotion
    op.execute("UPDATE capabilities SET signals_w = right_w + wrong_w")

    op.add_column("truth_signals", sa.Column("blame_vector", postgresql.JSONB()))
    op.add_column("truth_signals", sa.Column("component", sa.String(160)))
    op.add_column("truth_signals", sa.Column("gold_id", sa.String(36)))
    op.add_column("truth_signals", sa.Column("snapshot_id", sa.String(36)))
    op.add_column("truth_signals", sa.Column("disputed", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_index("ix_truth_signals_claim_kind", "truth_signals", ["claim_id", "kind"])
    op.drop_constraint("ck_signal_kind", "truth_signals", type_="check")
    op.create_check_constraint("ck_signal_kind", "truth_signals", _KINDS_011)

    op.create_table(
        "component_reputation",
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("key", sa.String(160), nullable=False),
        sa.Column("right_w", sa.Float(), nullable=False, server_default="0"),
        sa.Column("wrong_w", sa.Float(), nullable=False, server_default="0"),
        sa.Column("acc_lb", sa.Float(), nullable=False, server_default="0"),
        sa.Column("decayed_at", _TS, nullable=False),
        sa.PrimaryKeyConstraint("kind", "key"),
        sa.CheckConstraint("kind IN ('parser','extractor','relevance','rule','fusion')", name="ck_component_kind"),
    )
    op.create_table(
        "acq_daily",
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("area", sa.String(20), nullable=False),
        sa.Column("market", sa.String(8), nullable=False),
        sa.Column("searches", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pages", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("accepted_values", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("wrong_values", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("gold_checked", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("gold_wrong", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_eur", sa.Numeric(10, 4), nullable=False, server_default="0"),
        sa.Column("explore_eur", sa.Numeric(10, 4), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("day", "area", "market"),
    )
    op.create_table(
        "kpi_baselines",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(60), nullable=False, index=True),
        sa.Column("started_at", _TS, nullable=False),
        sa.Column("ended_at", _TS),
        sa.Column("values", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("recorded_at", _TS),
        sa.Column("note", sa.Text()),
    )


def downgrade() -> None:
    op.drop_table("kpi_baselines")
    op.drop_table("acq_daily")
    op.drop_table("component_reputation")
    op.execute("DELETE FROM truth_signals WHERE kind = 'physics'")
    op.drop_constraint("ck_signal_kind", "truth_signals", type_="check")
    op.create_check_constraint("ck_signal_kind", "truth_signals", _KINDS_010)
    op.drop_index("ix_truth_signals_claim_kind", table_name="truth_signals")
    for col in ("disputed", "snapshot_id", "gold_id", "component", "blame_vector"):
        op.drop_column("truth_signals", col)
    for col in ("explore_spent_eur", "families_agree", "signals_w"):
        op.drop_column("capabilities", col)
