"""The stored pages an attempt read (`acquisition.snapshots`): a page that gave accepted values is kept longer and
remembers the variant it served (spec 011 T021)."""

from __future__ import annotations

import logging

from automind.acquisition.snapshots import store

log = logging.getLogger(__name__)


class SnapshotMarks:
    """`PageMarks` over the snapshot store; never raises (bookkeeping never fails a job, a failure is logged)."""

    async def mark(self, snapshot_id: str, accepted_values: int, variant_id: str | None) -> None:
        """Note the accepted values and the variant of the page."""
        try:
            await store.mark(snapshot_id, accepted_values, variant_id)
        except Exception:  # noqa: BLE001 - bookkeeping never fails a job
            log.warning("snapshot.mark_failed id=%s", snapshot_id, exc_info=True)
