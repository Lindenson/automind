"""data repairs: service intervals in thousands/years, gearbox text, one-speed gear counts

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-02

Rows extracted before the 2026-11-02 fixes: intervals stored as "16" for 16,000 km or "5" months for 5 years
(one RAV4 cost EUR 513,672/year), and hybrid e-CVTs stored as a "1 speed" gearbox.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from automind.shared.vehicle.specs import normalize_transmission

    conn = op.get_bind()
    op.execute(
        """
        UPDATE maintenance_items SET interval_km = CASE
            WHEN interval_km BETWEEN 3 AND 300 THEN interval_km * 1000
            WHEN interval_km < 1000 OR interval_km > 300000 THEN NULL
            ELSE interval_km END
        WHERE interval_km IS NOT NULL
        """
    )
    op.execute(
        """
        UPDATE maintenance_items SET interval_months = interval_months * 12
        WHERE interval_months <= 15
          AND excerpt ~* '(year|años|año|anos|jahr)' AND excerpt !~* '(month|mes|monat)'
        """
    )
    op.execute("UPDATE maintenance_items SET interval_months = NULL WHERE interval_months < 1 OR interval_months > 240")
    for table, status_col in (("claims", "status"), ("spec_values", None)):
        rows = conn.execute(
            sa.text(f"SELECT id, value_text FROM {table} WHERE attribute = 'transmission' AND value_text IS NOT NULL")
        ).all()
        for rid, text in rows:
            norm = normalize_transmission(text)
            if norm is not None:
                conn.execute(sa.text(f"UPDATE {table} SET value_text = :v WHERE id = :i"), {"v": norm, "i": rid})
            elif status_col:
                conn.execute(sa.text("UPDATE claims SET status = 'REJECTED_UNIT' WHERE id = :i"), {"i": rid})
    op.execute(
        """
        UPDATE claims SET status = 'REJECTED_IMPLAUSIBLE', reject_rule = 'gear_count.ANY'
        WHERE attribute = 'gear_count' AND value_num < 2 AND status = 'ACCEPTED'
          AND variant_id IN (SELECT id FROM vehicle_variants WHERE powertrain <> 'BEV')
        """
    )
    op.execute(
        """
        UPDATE spec_values SET available = false
        WHERE attribute = 'gear_count' AND value_num < 2
          AND variant_id IN (SELECT id FROM vehicle_variants WHERE powertrain <> 'BEV')
        """
    )


def downgrade() -> None:
    pass  # data repairs are not reversed
