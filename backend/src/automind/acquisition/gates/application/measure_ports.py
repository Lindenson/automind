"""The measures of the gates (spec 011 US5, research R4, R14): old and new versions of a change on stored pages, the
relevance keyword measure, and the agents' budgets the model calls are charged to.

Errors: a measure that a change kind does not have raises `NoMeasure` (the gate waits, then abandons); a store
failure raises `GateStoreUnavailable`; an exhausted budget raises the budget's own error (the task stops)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Protocol

from automind.acquisition.domain import gates
from automind.acquisition.gates.domain.change import Change
from automind.acquisition.gates.domain.relevance_change import RelevanceResult
from automind.acquisition.snapshots.store import SnapshotRef
from automind.shared.contracts.llm import LLM

Charge = Callable[[float], Awaitable[None]]  # (euros) -> None; raises the budget's error when it is spent
MetricsPair = tuple[gates.Metrics, gates.Metrics]  # (old version, new version)


class NoMeasure(Exception):  # noqa: N818 - a state of a change, not a failure
    """This change has no offline measure (yet)."""


class Measure(Protocol):
    """Old and new versions measured on stored pages (readers offline, extractors cached within the budget)."""

    async def corpus(self, c: Change, now: datetime) -> list[SnapshotRef]:
        """The stored pages the replay gate compares on."""
        ...

    async def refs(self, ids: list[str]) -> list[SnapshotRef]:
        """The stored pages with these ids."""
        ...

    async def live_pages(self, c: Change, since: datetime) -> list[SnapshotRef]:
        """Pages the new version read live since `since` (parsers; other kinds are judged on signals)."""
        ...

    async def measure(self, c: Change, refs: list[SnapshotRef], *, since: datetime | None = None,
                      llm: LLM | None = None, charge: Charge | None = None) -> MetricsPair:  # fmt: skip
        """(old, new) metrics; yield over the pages fetched `since` when given. Raises `NoMeasure`."""
        ...

    async def degraded(self, c: Change) -> bool:
        """The object's running version is degraded (a repair: the KPI is the new version's own accuracy)."""
        ...


class RelevanceMeasure(Protocol):
    """The measure of a relevance keyword change (`domain.relevance_change`)."""

    async def measure(self, c: Change, since: datetime, until: datetime, *, limit: int, llm: LLM | None = None,
                      charge: Charge | None = None) -> RelevanceResult:  # fmt: skip
        """A relevance keyword change re-run on the pages judged in [since, until]."""
        ...


class Budget(Protocol):
    """An agent's daily budget."""

    async def charge(self, eur: float) -> None:
        """Spend; raises the budget's error when it is over."""
        ...

    async def remaining(self) -> float:
        """Euros left today."""
        ...


class Budgets(Protocol):
    """The agents' daily budgets."""

    def of(self, agent: str) -> Budget:
        """The agent's budget."""
        ...
