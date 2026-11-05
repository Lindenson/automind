"""agents, gates and overrides (spec 011 US5, data-model "Migration 0023"): prompt_versions (seeded with the current
extraction, relevance and validator prompt files), role_model_overrides, rule_overrides, acq_experiments,
change_blocks

Revision ID: 0024
Revises: 0023
Create Date: 2026-11-05
"""

import hashlib
import re
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0024"
down_revision: str | Sequence[str] | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TS = sa.DateTime(timezone=True)
_ID = sa.String(36)
PROMPTS = Path(__file__).resolve().parents[2] / "src" / "automind" / "orchestration" / "prompts"
_HEADER = re.compile(r"<!--\s*prompt:\s*([\w-]+)\s+v(\d+)", re.I)
_VERSIONED = ("candidate", "active", "superseded", "rejected")


def _seed_rows() -> list[dict]:
    """The file versions of the prompts agents may change (extract_*, relevance, validator), status active."""
    rows = []
    now = datetime.now(UTC)
    files = sorted(PROMPTS.glob("extract_*.md")) + [PROMPTS / "relevance.md", PROMPTS / "validator.md"]
    for f in files:
        if not f.is_file():
            continue
        text = f.read_text(encoding="utf-8").strip()
        m = _HEADER.search(text[:300])
        name, version = (m.group(1), int(m.group(2))) if m else (f.stem, 1)
        rows.append({
            "key": f"{name}@v{version}", "name": name, "version": version, "text": text,
            "text_hash": hashlib.sha256(text.encode("utf-8")).hexdigest()[:12], "base_key": None,
            "status": "active", "author": "seed", "change_id": None, "created_at": now, "activated_at": now,
        })  # fmt: skip
    return rows


def upgrade() -> None:
    status_ck = "status IN (" + ",".join(f"'{s}'" for s in _VERSIONED) + ")"
    t = op.create_table(
        "prompt_versions",
        sa.Column("key", sa.String(80), primary_key=True),
        sa.Column("name", sa.String(40), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("text_hash", sa.String(12), nullable=False),
        sa.Column("base_key", sa.String(80)),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("author", sa.String(40), nullable=False),
        sa.Column("change_id", _ID),
        sa.Column("created_at", _TS, nullable=False, server_default=sa.func.now()),
        sa.Column("activated_at", _TS),
        sa.UniqueConstraint("name", "version", name="uq_prompt_versions_name_version"),
        sa.CheckConstraint(status_ck, name="ck_prompt_version_status"),
    )
    op.create_index("uq_prompt_versions_active", "prompt_versions", ["name"], unique=True,
                    postgresql_where=sa.text("status = 'active'"))  # fmt: skip
    op.create_table(
        "role_model_overrides",
        sa.Column("id", _ID, primary_key=True),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("model", sa.String(80), nullable=False),
        sa.Column("change_id", _ID),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", _TS, nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("role IN ('extractor','validator','relevance')", name="ck_role_model_override_role"),
    )
    op.create_index("uq_role_model_overrides_active", "role_model_overrides", ["role"], unique=True,
                    postgresql_where=sa.text("active"))  # fmt: skip
    op.create_table(
        "rule_overrides",
        sa.Column("id", _ID, primary_key=True),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("value", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("change_id", _ID),
        sa.Column("created_at", _TS, nullable=False, server_default=sa.func.now()),
        sa.Column("activated_at", _TS),
        sa.CheckConstraint(status_ck, name="ck_rule_override_status"),
    )
    op.create_index("uq_rule_overrides_active", "rule_overrides", ["path"], unique=True,
                    postgresql_where=sa.text("status = 'active'"))  # fmt: skip
    op.create_table(
        "acq_experiments",
        sa.Column("change_id", _ID, sa.ForeignKey("acq_changes.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("phase", sa.String(8), nullable=False),
        sa.Column("started_at", _TS, nullable=False, server_default=sa.func.now()),
        sa.Column("ends_at", _TS),
        sa.Column("corpus", postgresql.ARRAY(sa.String(36)), nullable=False, server_default="{}"),
        sa.Column("pages_old", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pages_new", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("metrics_old", postgresql.JSONB()),
        sa.Column("metrics_new", postgresql.JSONB()),
        sa.Column("daily", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("decided_at", _TS),
        sa.Column("decision", sa.Text()),
        sa.CheckConstraint("phase IN ('replay','shadow','watch')", name="ck_experiment_phase"),
    )
    op.create_table(
        "change_blocks",
        sa.Column("object_kind", sa.String(20), nullable=False),
        sa.Column("object_key", sa.String(160), nullable=False),
        sa.Column("lever", sa.String(20), nullable=False),
        sa.Column("until", _TS),
        sa.Column("created_by", sa.String(40), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", _TS, nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("object_kind", "object_key", "lever"),
    )
    rows = _seed_rows()
    if rows:
        op.bulk_insert(t, rows)


def downgrade() -> None:
    op.drop_table("change_blocks")
    op.drop_table("acq_experiments")
    op.drop_index("uq_rule_overrides_active", table_name="rule_overrides")
    op.drop_table("rule_overrides")
    op.drop_index("uq_role_model_overrides_active", table_name="role_model_overrides")
    op.drop_table("role_model_overrides")
    op.drop_index("uq_prompt_versions_active", table_name="prompt_versions")
    op.drop_table("prompt_versions")
