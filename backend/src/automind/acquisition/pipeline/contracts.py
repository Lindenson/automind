"""What one research job is and what it gives back: the job (`JobSpec`), its result (`JobResult`), the progress
callback (`Emit`), what its searches found (`Found`) and what its pages gave (`PageOutcome`, `PageTally`)."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from automind.acquisition.registry.api import Outcome
from automind.shared.contracts.web import Page
from automind.shared.research_order import search_plan

Emit = Callable[[str, str], Awaitable[None]]  # (stage, text): a progress line for the person waiting


@dataclass
class JobSpec:
    job_id: str
    variant_id: str
    area: str
    round: int = 0
    car_year: int | None = None  # the user's car year (validator compares claims with the case, FR-016)
    fresh: bool = False  # the user asked to search again: bypass the search cache and widen the queries
    escalate: bool = False  # an area left short: round 0 also queries the registry's other markets (010 FR-022)
    market: str | None = None  # where the car is sold when not in Spain (CaseCar.market; chat 2026-11-06)

    @property
    def escalated(self) -> bool:
        """The job queries the registry's sources of the other markets (a follow-up round, "find it", a retry)."""
        return self.round > 0 or self.fresh or self.escalate


@dataclass
class JobResult:
    job_id: str
    variant_id: str
    area: str
    round: int
    ok: bool = True
    docs: int = 0
    accepted: int = 0
    rejected: int = 0
    minimum_met: bool = False
    error: str | None = None
    hits: list[dict[str, Any]] = field(default_factory=list)
    planned: list[str] = field(default_factory=list)  # the active sources of the registry's plan (not_reached input)


@dataclass(frozen=True)
class Found:
    """One job's whole search: the queries it ran, the pages it fetched and the search counts (`locate.collect`)."""

    planned: list[search_plan.PlannedQuery]
    pages: list[Page]
    stats: dict[str, Any]


@dataclass(frozen=True)
class PageOutcome:
    """A page as an attempt of its source (spec 010 FR-015): the outcome, why it was rejected, the values it gave."""

    outcome: Outcome
    reason: str | None = None
    values: int = 0


NO_VALUES = PageOutcome(Outcome.EMPTY)


@dataclass
class PageTally:
    """What a car area's pages gave: pages past relevance (`docs`), accepted and rejected values, values read by a
    table reader, pages rejected by relevance per verdict (`off_topic`), values rejected per reason, each page's
    outcome, and the pages a table reader read (`tabled`: never extracted)."""

    tabled: set[str] = field(default_factory=set)
    docs: int = 0
    accepted: int = 0
    rejected: int = 0
    reader: int = 0
    off_topic: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    values_rejected: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    outcomes: dict[str, PageOutcome] = field(default_factory=dict)

    def rejected_page(self, url: str, verdict: str) -> None:
        """The relevance rules or role said the page is about another car (or no car)."""
        self.off_topic[verdict.lower()] += 1
        self.outcomes[url] = PageOutcome(Outcome.REJECTED, verdict.lower())

    def stored(self, url: str, accepted: int, rejected: int) -> None:
        """A page's checked values were stored."""
        self.accepted += accepted
        self.rejected += rejected
        self.outcomes[url] = (
            PageOutcome(Outcome.ACCEPTED, None, accepted) if accepted
            else PageOutcome(Outcome.REJECTED, "values_rejected") if rejected else NO_VALUES
        )  # fmt: skip

    def shadow_pages(self, pages: list[Page]) -> list[Page]:
        """The shadow gate's feed: the pages with an outcome that no table reader read — the extracted ones and, as
        before the split, the ones relevance dropped (pages whose extraction failed have no outcome)."""
        return [p for p in pages if p.url not in self.tabled and p.url in self.outcomes]
