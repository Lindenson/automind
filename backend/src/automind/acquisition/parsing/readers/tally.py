"""What the site readers counted since the last flush (spec 011 T087): pages per site and day, each snapshot's
structure stamp, and every version's zero streak (pages in a row with no field). Pure, in memory."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

from automind.acquisition.parsing.readers.ports import SiteDay, Stamp
from automind.shared.contracts.site_readers import SiteReading

log = logging.getLogger(__name__)
STREAKS: dict[str, int] = {}  # reader -> pages in a row with no field, in this process (automind_reader_zero_streak)


@dataclass
class Streak:
    """A version's run of field-less pages, as this process saw it."""

    zeros: int = 0  # pages with no field since the last flush (after `reset`)
    reset: bool = False  # a page had fields since the last flush
    since: datetime | None = None  # first page of the current streak
    total: int = 0  # the streak as this process sees it

    def take(self) -> tuple[int, bool, datetime | None]:
        """(zeros, reset, since) to add to the stored streak; the pending part starts again."""
        got = (self.zeros, self.reset, self.since)
        self.zeros, self.reset = 0, False
        return got


@dataclass
class ReadingTally:
    """The counts of one registry between flushes."""

    broken_at: int  # the streak length that is logged once as "site_reader.broken"
    stats: dict[SiteDay, dict[str, int]] = field(default_factory=dict)
    streaks: dict[str, Streak] = field(default_factory=dict)
    snapshots: dict[str, Stamp] = field(default_factory=dict)  # snapshot id -> (structure hash, version key)

    def count(self, domain: str, key: str, reader: str, out: SiteReading | None, fields: int) -> None:
        """Count one page of `domain` read by version `key` of `reader`: its outcome and the zero streak."""
        day = datetime.now(UTC).date().isoformat()
        s = self.stats.setdefault((domain, day), {"ok": 0, "failed": 0, "ambiguous": 0})
        s["failed" if out is None else "ambiguous" if out.ambiguous else "ok"] += 1
        st = self.streaks.setdefault(key, Streak())
        if fields:
            st.zeros, st.reset, st.since, st.total = 0, True, None, 0
        else:
            st.zeros += 1
            st.total += 1
            st.since = st.since or datetime.now(UTC)
        STREAKS[reader] = st.total
        if st.total == self.broken_at:  # a redesign breaks label readers silently: say it once
            log.warning("site_reader.broken reader=%s domain=%s pages_in_a_row=%d", key, domain, st.total,
                        extra={"event": "site_reader.broken", "reader": key, "domain": domain})  # fmt: skip

    def take_stats(self) -> dict[SiteDay, dict[str, int]]:
        """The site counts to write; the tally starts again."""
        got, self.stats = self.stats, {}
        return got

    def take_snapshots(self) -> dict[str, Stamp]:
        """The snapshot stamps to write; the tally starts again."""
        got, self.snapshots = self.snapshots, {}
        return got
