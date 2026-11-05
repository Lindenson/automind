"""snapshots and producer versions (spec 011 US1, data-model "Migration 0018"): raw page snapshots (zstd, content
addressed), and the source, producer version, model and snapshot on every claim and registry attempt

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0018"
down_revision: str | Sequence[str] | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TS = sa.DateTime(timezone=True)

# the site readers of config/site_readers.yaml on 2026-11-05 (they become version 1 of their parser specs)
_BACKFILL_READER_VERSION = """
UPDATE claims c SET producer_version = CASE
    WHEN d.reader LIKE 'site:%' THEN substr(d.reader, 6) || '@v1'
    WHEN e.domain = 'km77.com' OR e.domain LIKE '%.km77.com' THEN 'km77@v1'
    WHEN e.domain = 'ultimatespecs.com' OR e.domain LIKE '%.ultimatespecs.com' THEN 'ultimatespecs@v1'
    WHEN e.domain = 'auto-data.net' OR e.domain LIKE '%.auto-data.net' THEN 'auto_data@v1'
    ELSE 'legacy' END
FROM evidence e JOIN documents d ON d.id = e.document_id
WHERE e.id = c.evidence_id AND c.producer = 'reader'
"""


def upgrade() -> None:
    op.create_table(
        "snapshot_blobs",
        sa.Column("sha256", sa.String(64), primary_key=True),
        sa.Column("codec", sa.String(8), nullable=False),
        sa.Column("body", sa.LargeBinary(), nullable=False),
        sa.Column("raw_bytes", sa.Integer(), nullable=False),
        sa.Column("stored_bytes", sa.Integer(), nullable=False),
        sa.Column("created_at", _TS, nullable=False),
    )
    op.execute("ALTER TABLE snapshot_blobs ALTER COLUMN body SET STORAGE EXTERNAL")  # zstd output: no TOAST pglz
    op.create_table(
        "page_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("url_hash", sa.String(64), nullable=False, index=True),
        sa.Column("final_url", sa.Text()),
        sa.Column("domain", sa.String(200), nullable=False, index=True),
        sa.Column("document_id", sa.String(36), sa.ForeignKey("documents.id", ondelete="SET NULL"), index=True),
        sa.Column("fetched_at", _TS, nullable=False, index=True),
        sa.Column("blob_sha256", sa.String(64), sa.ForeignKey("snapshot_blobs.sha256"), index=True),
        sa.Column("content_type", sa.String(60)),
        sa.Column("http_status", sa.Integer()),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("replayable", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("retention_class", sa.String(10), nullable=False, server_default="plain"),
        sa.Column("keep_until", _TS, index=True),
        sa.Column("accepted_values", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("variant_ids", postgresql.ARRAY(sa.String(36)), nullable=False, server_default="{}"),
        sa.Column("structure_hash", sa.String(16)),
        sa.Column("parser_version", sa.String(80)),
    )
    op.add_column("claims", sa.Column("producer", sa.String(12), nullable=False, server_default="extractor"))
    op.add_column("claims", sa.Column("producer_version", sa.String(80)))
    op.add_column("claims", sa.Column("model", sa.String(80)))
    op.add_column(
        "claims",
        sa.Column("snapshot_id", sa.String(36), sa.ForeignKey("page_snapshots.id", ondelete="SET NULL")),
    )
    op.create_index("ix_claims_snapshot_id", "claims", ["snapshot_id"])
    op.add_column("registry_attempts", sa.Column("producer_version", sa.String(80)))
    op.add_column("registry_attempts", sa.Column("model", sa.String(80)))
    op.add_column("registry_attempts", sa.Column("snapshot_id", sa.String(36)))
    op.add_column(
        "registry_attempts",
        sa.Column("stage_versions", postgresql.JSONB(), nullable=False, server_default="{}"),
    )
    op.add_column("registry_attempts", sa.Column("searches", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("page_relevance", sa.Column("prompt_version", sa.String(80)))
    op.add_column("page_relevance", sa.Column("model", sa.String(80)))
    op.add_column(
        "research_runs", sa.Column("stage_versions", postgresql.JSONB(), nullable=False, server_default="{}")
    )
    # back-fill (FR-002): readers name their reader as version 1, model claims are "legacy"
    op.execute("UPDATE claims SET producer = CASE WHEN extracted_by = 'READER' THEN 'reader' ELSE 'extractor' END")
    op.execute("UPDATE claims SET producer_version = 'legacy' WHERE producer = 'extractor'")
    op.execute(_BACKFILL_READER_VERSION)


def downgrade() -> None:
    op.drop_column("research_runs", "stage_versions")
    op.drop_column("page_relevance", "model")
    op.drop_column("page_relevance", "prompt_version")
    for col in ("searches", "stage_versions", "snapshot_id", "model", "producer_version"):
        op.drop_column("registry_attempts", col)
    op.drop_index("ix_claims_snapshot_id", table_name="claims")
    for col in ("snapshot_id", "model", "producer_version", "producer"):
        op.drop_column("claims", col)
    op.drop_table("page_snapshots")
    op.drop_table("snapshot_blobs")
