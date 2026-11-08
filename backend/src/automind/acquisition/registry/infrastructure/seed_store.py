"""The registry's first content (`sources`, `capabilities`, `registry_changes`; spec 010 US8). Writes the access
verdicts of the owner's favourites and the survey (a human-only setting: tests/unit/test_no_self_change.py allows
this module). Every method raises `RegistryStoreUnavailable` when the database fails; `seed` is one transaction."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from automind.acquisition.registry.application.ports import RegistryStoreUnavailable
from automind.acquisition.registry.domain.model import Capability, Source
from automind.shared.infrastructure.db.errors import translate_errors
from automind.shared.infrastructure.db.models import CapabilityRow, RegistryChange, SourceRow, now
from automind.shared.infrastructure.db.session import sessionmaker

UNJUDGED = ("ok", "unknown")


class SeedStore:
    """`SeedBook` over the database."""

    @translate_errors(RegistryStoreUnavailable)
    async def is_empty(self) -> bool:
        """No source is stored yet."""
        async with sessionmaker()() as s:
            return (await s.execute(select(SourceRow.domain).limit(1))).first() is None

    @translate_errors(RegistryStoreUnavailable)
    async def seed(self, items: Iterable[tuple[Source, Sequence[Capability]]], reason: str) -> int:
        """Insert what is missing; blocked always wins over other statuses of the same capability. Journalled."""
        added = 0
        async with sessionmaker()() as s:
            for src, caps in items:
                await _source(s, src)
                for c in caps:
                    added += await _capability(s, c, src, reason)
            await s.commit()
        return added


async def _source(s: AsyncSession, src: Source) -> None:
    row = await s.get(SourceRow, src.domain)
    if row is None:
        s.add(SourceRow(domain=src.domain, source_type=src.source_type, family=src.family, markets=src.markets,
                        languages=src.languages, access=src.access, access_evidence=src.access_evidence,
                        reader=src.reader))  # fmt: skip
        await s.flush()
    elif src.access not in UNJUDGED and row.access in UNJUDGED:
        row.access, row.access_evidence = src.access, src.access_evidence
    elif src.reader and not row.reader:
        row.reader = src.reader


async def _capability(s: AsyncSession, c: Capability, src: Source, reason: str) -> int:
    """1 when the capability was added; a blocked seed blocks a stored one; a missing seed priority is filled."""
    q = select(CapabilityRow).where(
        CapabilityRow.domain == c.domain, CapabilityRow.area == c.area, CapabilityRow.market == c.market
    )
    have = (await s.execute(q)).scalar_one_or_none()
    if have is None:
        cap = CapabilityRow(domain=c.domain, area=c.area, market=c.market, status=c.status,
                            priority_seed=c.priority_seed, attempts=c.attempts, accepted=c.accepted)  # fmt: skip
        s.add(cap)
        await s.flush()
        s.add(RegistryChange(author="system", capability_id=cap.id, domain=c.domain, change="added",
                             after={"status": c.status, "area": c.area, "market": c.market}, reason=reason,
                             evidence=src.access_evidence))  # fmt: skip
        return 1
    if c.status == "blocked" and have.status != "blocked":
        before = have.status
        have.status, have.status_since = "blocked", now()
        s.add(RegistryChange(author="system", capability_id=have.id, domain=c.domain, change="blocked",
                             before={"status": before}, after={"status": "blocked"}, reason=reason,
                             evidence=src.access_evidence))  # fmt: skip
    elif have.priority_seed is None and c.priority_seed is not None:
        have.priority_seed = c.priority_seed
    return 0
