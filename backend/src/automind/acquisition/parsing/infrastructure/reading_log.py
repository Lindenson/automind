"""The log of what the site readers read (spec 011 T087): page counts per site and day (`site_reader_stats`) and
each snapshot's structure hash and parser version (`page_snapshots`). Implements `ReadingLog`.

Errors: `ParserStoreUnavailable` when the database fails; each call is one transaction (nothing half written).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert

from automind.acquisition.parsing.readers.ports import ParserStoreUnavailable, SiteDay, Stamp
from automind.shared.infrastructure.db import PageSnapshot, SiteReaderStat
from automind.shared.infrastructure.db.errors import translate_errors
from automind.shared.infrastructure.db.session import sessionmaker


class ReadingLogStore:
    """`site_reader_stats` and the parser columns of `page_snapshots`."""

    @translate_errors(ParserStoreUnavailable)
    async def add_site_stats(self, counts: Mapping[SiteDay, Mapping[str, int]]) -> None:
        """Add the counts to each site's row of the day (created when missing)."""
        async with sessionmaker()() as s:
            for (domain, day), n in counts.items():
                stmt = insert(SiteReaderStat).values(domain=domain, day=datetime.fromisoformat(day).date(), **n)
                await s.execute(stmt.on_conflict_do_update(
                    index_elements=["domain", "day"],
                    set_={k: getattr(SiteReaderStat, k) + stmt.excluded[k] for k in n},
                ))  # fmt: skip
            await s.commit()

    @translate_errors(ParserStoreUnavailable)
    async def stamp_snapshots(self, stamps: Mapping[str, Stamp]) -> None:
        """Store `structure_hash` and `parser_version` on each snapshot."""
        async with sessionmaker()() as s:
            for sid, (h, key) in stamps.items():
                await s.execute(update(PageSnapshot).where(PageSnapshot.id == sid)
                                .values(structure_hash=h, parser_version=key))  # fmt: skip
            await s.commit()
