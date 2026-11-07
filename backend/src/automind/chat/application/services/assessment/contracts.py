"""Contracts of the assessment service: the cars assessed, the request to plan the research, what earlier research
left (the planner's inputs, read once), and the result with the shape it writes into the turn state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, TypedDict

from automind.chat.application.services.identification.contracts import Assessment
from automind.chat.application.services.report.blocks.notice import Notice
from automind.chat.application.services.research.contracts import PlanRow, PlanState
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


class AssessedState(TypedDict, total=False):
    """What the assessment writes into the turn state. `feasibility` and `notices` only when there is something new:
    an earlier assess of the same turn may have set them; `case_version` when the case was saved."""

    case_version: int
    assessments: dict[str, JsonObject]
    research_plan: PlanState
    cost_estimate: float
    research_declined: bool
    feasibility: JsonObject
    notices: list[Notice]


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

    def to_state(self, notices: list[Notice]) -> AssessedState:
        """The turn state update; `notices` are the turn's notices so far (the new warnings are appended)."""
        rows: list[PlanRow] = [[j.car_key, j.variant_id, j.area, j.fresh, j.escalate] for j in self.plan.jobs]
        out: AssessedState = {
            "assessments": {k: a.model_dump(mode="json") for k, a in self.assessments.items()},
            "research_plan": {"jobs": rows, "rounds": self.plan.rounds, "key": self.plan_key},
            "cost_estimate": self.cost_eur,
            "research_declined": self.declined,
        }
        if self.feasibility is not None:
            out["feasibility"] = self.feasibility
        if self.warnings:
            out["notices"] = [*notices, *self.warnings]
        return out
