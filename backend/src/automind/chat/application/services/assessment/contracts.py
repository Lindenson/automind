"""Contracts of the assessment service: the cars assessed, the request to plan the research, what earlier research
left (the planner's inputs, read once), and the result (`Planned`; what it writes into the turn state is the
dialog's node contract)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from automind.chat.application.services.identification.contracts import Assessment
from automind.chat.application.services.report.blocks.notice import Notice
from automind.chat.domain.case import CaseFile
from automind.shared.contracts.json import JsonObject
from automind.shared.research_order.plan import ResearchPlan, WarningKind


class PlanWording(Protocol):
    """The words of the plan's warnings (implemented by `dialog.report_wording.DialogWording`)."""

    def plan_warning(self, kind: WarningKind, label: str) -> str:
        """The warning of `kind` about the car `label`."""
        ...


@dataclass(frozen=True)
class CarsAssessed:
    """Every car of the case looked up in the catalogue (car key -> assessment) and what changed in the case: the
    comparison level, a version dropped or split, a car auto-resolved. The case is saved when `changes` is not
    empty."""

    assessments: dict[str, Assessment]
    changes: list[str]


@dataclass(frozen=True)
class PlanRequest:
    """The research to plan for the assessed case. `research_more`: the person asked to find what is missing ("find
    it", a critique), so areas below their minimum are tried again, deeper; `focus` (car keys) and `areas` narrow
    it. `shown`: the notice texts the turn already shows (a warning is given once)."""

    case: CaseFile
    assessments: dict[str, Assessment]
    research_more: bool = False
    focus: tuple[str, ...] = ()
    areas: tuple[str, ...] = ()
    shown: frozenset[str] = frozenset()


@dataclass(frozen=True)
class PlanHistory:
    """What earlier research left for the cars to plan (`ports.ResearchHistory`, `ports.MarketFacts`), read once."""

    powertrains: dict[str, str | None]
    last_done: dict[str, dict[str, datetime]]
    unmet: dict[str, set[str]]
    registry_done: dict[str, dict[str, datetime]]
    market_done: datetime | None  # the market's incentives, one date for every car (spec 006 US5)


@dataclass(frozen=True)
class Planned:
    """The assessed cars with the freshness the plan implies, the research plan, its cost in euros, whether the
    person already declined this very plan, the feasibility checks (None: not run) and the new warnings."""

    assessments: dict[str, Assessment]
    plan: ResearchPlan
    plan_key: str
    cost_eur: float
    declined: bool
    feasibility: JsonObject | None
    warnings: list[Notice]
