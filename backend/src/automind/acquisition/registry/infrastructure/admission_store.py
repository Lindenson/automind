"""The admission book (`sources`, `capabilities`, `registry_changes`, and the `terms_reader` spend in `llm_calls`;
spec 010 US7, FR-019). Writes the access verdicts of the admission check (a human-only setting:
tests/unit/test_no_self_change.py allows this module). Every method raises `RegistryStoreUnavailable` when the
database fails; `record_verdict` is one transaction."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import or_, select, text

from automind.acquisition.registry.application.ports import RegistryStoreUnavailable
from automind.acquisition.registry.domain.admission import Admission
from automind.shared.infrastructure.db.errors import translate_errors
from automind.shared.infrastructure.db.models import CapabilityRow, RegistryChange, SourceRow
from automind.shared.infrastructure.db.session import sessionmaker
from automind.shared.infrastructure.metrics import prom

ADMITTING = ("ok", "unknown")
TERMS_SPENT = text("SELECT coalesce(sum(cost_eur),0) FROM llm_calls WHERE role = 'terms_reader' AND created_at >= :s")


class AdmissionStore:
    """`AdmissionBook` over the database."""

    @translate_errors(RegistryStoreUnavailable)
    async def due(self, limit: int, now: datetime) -> list[str]:
        """Domains with a discovered capability or a re-check due, not frozen; at most `limit`."""
        async with sessionmaker()() as s:
            discovered = select(CapabilityRow.domain).where(CapabilityRow.status == "discovered")
            q = (
                select(SourceRow.domain)
                .where(
                    or_(SourceRow.domain.in_(discovered), SourceRow.next_check_at < now), SourceRow.frozen.is_(False)
                )
                .limit(limit)
            )
            return list((await s.execute(q)).scalars())

    @translate_errors(RegistryStoreUnavailable)
    async def record_verdict(self, domain: str, verdict: Admission, next_check_at: datetime,
                             now: datetime) -> str | None:  # fmt: skip
        """Write the access, its evidence and the next re-check; journal a change of access (author "system").
        Returns the access before the check, None when the source does not exist."""
        async with sessionmaker()() as s:
            row = await s.get(SourceRow, domain)
            if row is None:
                return None
            before = row.access
            row.access, row.checked_at = verdict.access, now
            row.access_evidence = {**(row.access_evidence or {}), **verdict.evidence}
            row.next_check_at = next_check_at
            if before != verdict.access:
                change = "admitted" if verdict.access in ADMITTING else "blocked"
                s.add(RegistryChange(author="system", domain=row.domain, change=change, before={"access": before},
                                     after={"access": verdict.access}, reason=f"admission check: {verdict.reason}",
                                     evidence=verdict.evidence))  # fmt: skip
                prom.inc("registry_changes", change=change, author="system")
            await s.commit()
            return before

    @translate_errors(RegistryStoreUnavailable)
    async def terms_spent_since(self, since: datetime) -> float:
        """What the `terms_reader` role cost since `since` (EUR)."""
        async with sessionmaker()() as s:
            return float((await s.execute(TERMS_SPENT, {"s": since})).scalar() or 0)
