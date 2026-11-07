"""Contracts of the report service: the car as the report reads it, what it returns, what the text check is given,
and the two things it needs from the dialog — the wording in the person's language and the intake log (metrics).
Blocks are JSON documents for the UI (`JsonObject`); everything the report reads back is typed."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol, TypedDict

from automind.acquisition.api import CatalogueVariant
from automind.acquisition.api.car import (
    EvidenceRow,
    IssueRow,
    MaintenanceRow,
    ManufacturerFactRow,
    ReliabilityStatRow,
    ResearchRunRow,
    RetentionRow,
    ReviewRow,
    SpecValueRow,
)
from automind.chat.domain.assessment.criteria import CriteriaScore
from automind.chat.domain.assessment.dragrace import RaceResult
from automind.chat.domain.case import CaseCar, CaseFile
from automind.chat.domain.cost.tco import TcoEstimate
from automind.chat.domain.identification import used
from automind.chat.domain.verdict.insights import InsightSet
from automind.chat.domain.verdict.suggestions import Suggestion
from automind.chat.domain.verdict.verdict import Verdict
from automind.shared.contracts.json import JsonObject


class LoadedCar(TypedDict):
    """One car as the report reads it (`facts.car.load_car`): its catalogue version, its stored values and the
    sources behind them, the research runs and what each area read, and the rows of each research area."""

    variant: CatalogueVariant
    values: dict[str, SpecValueRow]  # attribute -> the selected value
    cltc_pair: tuple[float, float, str] | None  # CLTC and WLTP range of one source (an EV from China)
    claim_src: dict[str, JsonObject]  # claim id -> its source as the UI shows it
    rejected_pages: list[JsonObject]  # pages read and rejected, as the UI shows them
    researched_at: str | None  # ISO time of the last research run
    runs: dict[str, ResearchRunRow]  # area -> its last run
    tried: dict[str, list[JsonObject]]  # area -> the sources read (T123)
    issues: list[tuple[IssueRow, EvidenceRow]]
    reviews: list[tuple[ReviewRow, EvidenceRow]]
    manufacturer_facts: list[ManufacturerFactRow]
    stats: list[ReliabilityStatRow]
    retention: list[tuple[RetentionRow, EvidenceRow | None]]
    used_prices: list[used.UsedRange]  # sourced used-price ranges (spec 008)
    maintenance: list[MaintenanceRow]  # sourced maintenance items (the ownership cost)
    used_issues: list[IssueRow]  # issues of used cars with an age or mileage (the ownership cost)


KeyedCars = Sequence[tuple[CaseCar, LoadedCar]]  # the case's identified cars, each with its loaded data

Curves = Mapping[str, Mapping[float, float]]  # config/feasibility.yaml depreciation: class -> years -> share kept

SameData = Callable[[CaseFile], tuple[str | None, bool]]
"""(a case with other weights) -> (winner, tie) on the same data (spec 007 FR-006/FR-018)."""


class ReportWording(Protocol):
    """The report decides what to say; the dialog says it in the person's language (`chat.dialog.phrases`,
    `chat.dialog.report_text`). Numbers come from the report, never from the wording."""

    def t(self, key: str, lang: str | None, **params: object) -> str:
        """The phrase `key` with its parameters filled in."""
        ...

    def energy_input(self, name: str, lang: str | None) -> str:
        """The name of an input of the energy cost (consumption, price per kWh, …)."""
        ...

    def market_name(self, code: str | None, lang: str | None) -> str:
        """The name of a market ("ES", "EU", "CN", a country)."""
        ...

    def thousands(self, value: float, lang: str | None) -> str:
        """A number with the person's thousands separator."""
        ...

    def verdict_block(self, v: Verdict, s: InsightSet, names: Mapping[str, str], lang: str | None,
                      years: int | None = None) -> JsonObject:  # fmt: skip
        """The verdict card (`names`: car id -> short name; `years`: the ownership period)."""
        ...

    def profile_lines(self, v: Verdict, names: Mapping[str, str], lang: str | None,
                      years: int | None = None) -> list[str]:  # fmt: skip
        """What the person's profile changes in the verdict, as lines for the writer."""
        ...

    def insights_for_llm(self, s: InsightSet, v: Verdict, names: Mapping[str, str], lang: str | None,
                         years: int | None = None) -> JsonObject:  # fmt: skip
        """The insights and the verdict as the writer's facts."""
        ...

    def electric_lines(self, block: JsonObject | None, break_even: JsonObject | None, names: Mapping[str, str],
                       lang: str | None, *, years_said: bool = False) -> list[str]:  # fmt: skip
        """The electric block and the break-even as lines for the writer."""
        ...

    def suggestions_block(self, items: list[Suggestion], names: Mapping[str, str],
                          lang: str | None) -> JsonObject | None:  # fmt: skip
        """The one-click next steps (spec 004 FR-020), None when there are none."""
        ...


@dataclass(frozen=True)
class CheckInput:
    """What the text check (chat.dialog.guard) compares the writer's text with."""

    has_data: frozenset[str]  # topics with data in the blocks (TOPIC_WORDS keys)
    ties: frozenset[str]  # insight attributes whose cars are about the same
    tie: bool  # the verdict is a tie
    car_names: tuple[str, ...]  # short names of the cars as the text may write them
    costlier: tuple[str, ...] = ()  # short names of the cars whose total over the period (incl. depreciation) is higher


@dataclass
class Computed:
    """A report computed from stored data: ordered blocks, the writer's facts and what the dialog checks with."""

    blocks: list[JsonObject]
    facts: JsonObject  # the writer's facts (sent to the model as JSON)
    criteria: CriteriaScore | None
    cars: list[LoadedCar] = field(default_factory=list)
    tco: list[TcoEstimate] = field(default_factory=list)
    race: RaceResult | None = None
    insights: InsightSet | None = None  # spec 004 US3
    verdict: Verdict | None = None  # spec 004 US1
    check: CheckInput | None = None  # the input of the report check
    outcome: SameData | None = None  # questions by value (spec 007 FR-006)
