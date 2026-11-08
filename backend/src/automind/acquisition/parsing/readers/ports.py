"""What the live site readers need from outside (spec 011 T087): the stored parser versions, the log of what they
read, and the shadow gate's feed. Implemented in `parsing/infrastructure/` (`wiring.parser_registry()`).

Errors: every store method raises `ParserStoreUnavailable` when the database fails, never a driver exception. The
registry keeps the readers it has when a refresh fails and drops a bookkeeping step that fails (a job never fails on
them).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any, Protocol

from automind.acquisition.domain.drift import Drift
from automind.acquisition.parsing.readers.versions import Version

SiteDay = tuple[str, str]  # (domain, ISO day)
Stamp = tuple[str, str]  # (structure hash, version key) of a page snapshot


class ParserStoreUnavailable(Exception):
    """The parser store (versions, reading log) could not be read or written."""


class ParserBook(Protocol):
    """The stored parser versions."""

    async def running(self) -> list[Version]:
        """The version each parser runs (active or degraded); a stored spec that no longer validates is skipped."""
        ...

    async def allowed_domains(self, domains: list[str]) -> set[str]:
        """The domains whose registry source has access "ok"."""
        ...

    async def add_zero_streak(self, key: str, zeros: int, reset: bool) -> tuple[int, str] | None:
        """Add `zeros` field-less pages to the version's streak (after a reset); (streak, status), None if unknown."""
        ...

    async def degrade(self, key: str, drift: Drift, *, since: datetime | None = None,
                      evidence: dict[str, Any] | None = None) -> str | None:  # fmt: skip
        """Degrade an active version, journal it and queue the parser doctor; the change id, None if not active."""
        ...


class ReadingLog(Protocol):
    """Where the counts of the reads go."""

    async def add_site_stats(self, counts: Mapping[SiteDay, Mapping[str, int]]) -> None:
        """Add ok/failed/ambiguous page counts per site and day (`site_reader_stats`)."""
        ...

    async def stamp_snapshots(self, stamps: Mapping[str, Stamp]) -> None:
        """Store each snapshot's structure hash and the version that read it."""
        ...


class ReadShadow(Protocol):
    """The shadow gate's feed of read pages (spec 011 T102)."""

    async def notify_read(self, read: Mapping[str, str]) -> None:
        """Queue the read snapshots (id → version key) for the parser and rule changes in shadow."""
        ...
