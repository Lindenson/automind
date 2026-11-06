"""Contracts of the report service: what it returns, what the text check is given, and the two things it needs
from the dialog — the wording in the person's language and the intake log (metrics)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from automind.chat.domain.assessment.criteria import CriteriaScore
from automind.chat.domain.verdict.insights import InsightSet
from automind.chat.domain.verdict.verdict import Verdict

IntakeLog = Callable[..., Awaitable[None]]
"""(kind, **details) -> None: one intake event (spec 005 R13), metrics only; never fails the report."""


class ReportWording(Protocol):
    """The report decides what to say; the dialog says it in the person's language (`chat.dialog.phrases`,
    `chat.dialog.report_text`). Numbers come from the report, never from the wording."""

    def t(self, key: str, lang: str | None, **params: object) -> str: ...

    def energy_input(self, name: str, lang: str | None) -> str: ...

    def market_name(self, code: str | None, lang: str | None) -> str: ...

    def thousands(self, value: float, lang: str | None) -> str: ...

    def verdict_block(self, v: Verdict, s: InsightSet, names: Mapping[str, str], lang: str | None,
                      years: int | None = None) -> dict[str, Any]: ...  # fmt: skip

    def profile_lines(self, v: Verdict, names: Mapping[str, str], lang: str | None,
                      years: int | None = None) -> list[str]: ...  # fmt: skip

    def insights_for_llm(self, s: InsightSet, v: Verdict, names: Mapping[str, str], lang: str | None,
                         years: int | None = None) -> dict[str, Any]: ...  # fmt: skip

    def electric_lines(self, block: Mapping[str, Any] | None, break_even: Mapping[str, Any] | None,
                       names: Mapping[str, str], lang: str | None, *,
                       years_said: bool = False) -> list[str]: ...  # fmt: skip

    def suggestions_block(self, items: list[Any], names: Mapping[str, str],
                          lang: str | None) -> dict[str, Any] | None: ...  # fmt: skip


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

    blocks: list[dict[str, Any]]
    facts: dict[str, Any]
    criteria: CriteriaScore | None
    cars: list[dict[str, Any]] = field(default_factory=list)
    tco: list[Any] = field(default_factory=list)
    race: Any = None
    insights: Any = None  # domain.insights.InsightSet (spec 004 US3)
    verdict: Any = None  # domain.verdict.Verdict (spec 004 US1)
    check: CheckInput | None = None  # the input of the report check
    outcome: Any = None  # (CaseFile) -> (winner, tie) on the same data: questions by value (spec 007 FR-006)
