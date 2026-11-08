"""The ports of the registry's services: the capabilities and their attempts, truth signals, the admission book, the
review's unit of work, the seed, the facts gathered about a site, the stored pages and the clock.

Errors: every store raises `RegistryStoreUnavailable` when its database fails, with the cause chained; each write is
one transaction, so a failed one leaves the registry as it was. `SiteFacts.gather` and `PageMarks.mark` say below
what they raise."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from contextlib import AbstractAsyncContextManager
from datetime import datetime
from typing import Protocol

from automind.acquisition.registry.api import Attempt, TruthSignalIn
from automind.acquisition.registry.domain.admission import Admission, AdmissionFacts
from automind.acquisition.registry.domain.model import Capability, Source
from automind.acquisition.registry.domain.records import CapabilityView, ReviewedCapability
from automind.acquisition.registry.domain.review import ReviewFacts, ReviewPlan


class RegistryStoreUnavailable(RuntimeError):
    """A registry store could not read or write (its database); the cause is chained."""


class Capabilities(Protocol):
    """The capabilities of the sources (`capabilities` joined with `sources`) and the attempts made on them."""

    async def capabilities(self, area: str, markets: list[str]) -> list[CapabilityView]:
        """Every capability of the area on these markets, with its source's type and access."""
        ...

    async def queryable(self, area: str, markets: list[str]) -> list[CapabilityView]:
        """Active and candidate capabilities of the area on these markets, with their source's access."""
        ...

    async def explore_spent(self) -> float:
        """Today's exploration spend over all capabilities (reset by the daily roll-up)."""
        ...

    async def record(self, attempts: list[Attempt]) -> None:
        """Count the attempts on their capabilities (a domain met for the first time is added as `discovered`) and
        journal each one, in one transaction."""
        ...


class Signals(Protocol):
    """Truth signals: recorded, applied to the capability's accuracy and to the blamed components."""

    async def signal(self, s: TruthSignalIn, weight: float) -> str:
        """Record and apply a signal (a disputed one is recorded only); returns its id."""
        ...

    async def resolve(self, signal_id: str, vector: dict[str, float], components: dict[str, str], note: str) -> bool:
        """Settle a disputed signal with its final blame vector and apply it; False when it is not disputed."""
        ...


class PageMarks(Protocol):
    """The stored pages an attempt read."""

    async def mark(self, snapshot_id: str, accepted_values: int, variant_id: str | None) -> None:
        """Note the accepted values and the variant of a page (kept longer). Never raises: bookkeeping only."""
        ...


class AdmissionBook(Protocol):
    """The sites waiting for an admission check and the verdicts written for them."""

    async def due(self, limit: int, now: datetime) -> list[str]:
        """Domains with a discovered capability or a re-check due, not frozen; at most `limit`."""
        ...

    async def record_verdict(self, domain: str, verdict: Admission, next_check_at: datetime,
                             now: datetime) -> str | None:  # fmt: skip
        """Write the access, its evidence and the next re-check; journal a change of access. Returns the access
        before the check, None when the source does not exist."""
        ...

    async def terms_spent_since(self, since: datetime) -> float:
        """What the `terms_reader` role cost since `since` (EUR)."""
        ...


class SiteFacts(Protocol):
    """The facts of an admission check, gathered from the site."""

    async def gather(self, domain: str, sample_url: str | None) -> AdmissionFacts:
        """Robots for the sample page (or the home page), readable content, the terms of use. May raise anything
        the network or the model raises: the caller treats it as "no verdict"."""
        ...


class ReviewSession(Protocol):
    """One review run in one transaction: committed when the block ends without an error, rolled back otherwise."""

    async def load(self) -> tuple[list[ReviewedCapability], ReviewFacts]:
        """Every capability faded and rescored to now, with the sources' state and the owner's reverts."""
        ...

    def apply(self, plan: ReviewPlan) -> None:
        """Stage the moves, the journal and the run's count of changes (written when the block ends)."""
        ...


class ReviewBook(Protocol):
    """Opens review runs."""

    def session(self, kind: str) -> AbstractAsyncContextManager[ReviewSession]:
        """A review run of this kind ("daily", "manual", …), journalled in `registry_runs`."""
        ...


class SeedBook(Protocol):
    """The registry's first content."""

    async def is_empty(self) -> bool:
        """No source is stored yet."""
        ...

    async def seed(self, items: Iterable[tuple[Source, Sequence[Capability]]], reason: str) -> int:
        """Insert what is missing (a blocked status always wins), journalled with `reason`; returns how many
        capabilities were added."""
        ...


class Clock(Protocol):
    """The time now (UTC)."""

    def now(self) -> datetime:
        """Now."""
        ...
