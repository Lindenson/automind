"""The assessment service (spec 012 S9c): what code knows about the case's cars before the policy decides.

`cars` checks every car against the catalogue — the comparison's equipment level, a version set earlier checked
again, the car looked up and auto-resolved when one version clearly wins — and changes the case in place; the caller
saves it when there are changes, before the plan is made. `plan` makes the case-driven research plan from what
earlier research left, prices it, says whether the person already declined this very plan, runs the feasibility
checks when the plan has nothing to research, and words the plan's warnings.

Failures: a store that cannot be read (`StoreUnavailable` from the research history, the market facts, the
estimator or the feasibility store) propagates; nothing is written here, so the turn resumes from its checkpoint
and assesses again. The feasibility checks run only with a feasibility store (None: the checks are off)."""

from __future__ import annotations

from automind.chat.application.ports import Clock, Estimator, MarketFacts, ResearchHistory
from automind.chat.application.services.assessment.contracts import (
    CarsAssessed,
    PlanHistory,
    Planned,
    PlanRequest,
    PlanWording,
)
from automind.chat.application.services.assessment.stages.car_checked import car_checked
from automind.chat.application.services.assessment.stages.research_plan import research_plan_for, variants_to_plan
from automind.chat.application.services.assessment.stages.warnings import new_warnings
from automind.chat.application.services.feasibility import feasibility as fz
from automind.chat.application.services.feasibility.feasibility import FeasibilityStore
from automind.chat.application.services.identification import revalidation
from automind.chat.application.services.identification.contracts import Assessment
from automind.chat.domain.case import CaseFile
from automind.shared.contracts.config import Reference
from automind.shared.contracts.json import JsonObject
from automind.shared.research_order import plan as research_order
from automind.shared.research_order.plan import ResearchPlan


class AssessmentService:
    """Assesses the case's cars and plans their research, with the reference data, the research history, the cost
    estimator, the clock, the market facts and the feasibility store (both optional) and the plan's wording."""

    def __init__(self, ref: Reference, research: ResearchHistory, estimator: Estimator, clock: Clock,
                 words: PlanWording, market_facts: MarketFacts | None = None,
                 feasibility: FeasibilityStore | None = None) -> None:  # fmt: skip
        self.ref, self.research, self.estimator, self.clock, self.words = ref, research, estimator, clock, words
        self.market_facts, self.feasibility = market_facts, feasibility

    async def cars(self, case: CaseFile, year: int) -> CarsAssessed:
        """Every car checked and looked up, in place (see the module docstring); `year` is the current year."""
        level, source = await revalidation.compare_level(case.cars)
        changes: list[str] = []
        if (level, source) != (case.compare_level, case.compare_level_source):
            case.compare_level, case.compare_level_source = level, source
            changes.append(f"comparison level: {level.lower()}")
        assessments: dict[str, Assessment] = {}
        for car in case.cars:
            assessments[car.key], changed = await car_checked(car, self.ref, year, level)
            changes += changed
        return CarsAssessed(assessments, changes)

    async def plan(self, req: PlanRequest) -> Planned:
        """The research plan for the assessed case, its cost and what follows from it (see the module docstring)."""
        case = req.case
        plan = research_plan_for(req, await self._history(case), self.clock.now(), self.ref.registry)
        key = research_order.plan_key(plan)
        cost = await self.estimator.estimate([(j.variant_id, j.area) for j in plan.jobs], plan.rounds)
        # Decided on every assess: the plan can grow inside a turn (a car confirmed after the first assess), and a
        # refusal of the smaller plan must not block research for the new one.
        declined = bool(plan.jobs) and case.declined_plan == key
        return Planned(
            _freshness(req.assessments, case, plan), plan, key, cost, declined, await self._feasibility(case, plan),
            new_warnings(plan, case, req.shown, self.words),
        )  # fmt: skip

    async def _history(self, case: CaseFile) -> PlanHistory:
        """What earlier research left for the versions to plan, read once."""
        ids = variants_to_plan(case)
        market = await self.market_facts.done() if self.market_facts is not None else None
        return PlanHistory(
            powertrains=await self.research.powertrains(ids), last_done=await self.research.last_done(ids),
            unmet=await self.research.unmet_areas(ids), registry_done=await self.research.registry_done(ids),
            market_done=market,
        )  # fmt: skip

    async def _feasibility(self, case: CaseFile, plan: ResearchPlan) -> JsonObject | None:
        """The feasibility checks (spec 003 US3), when the person set constraints and every car is identified with
        nothing left to research; None when they do not run."""
        if self.feasibility is None or not fz.has_constraints(case) or not case.cars or plan.jobs:
            return None
        if not all(x.variant_id for x in case.cars):
            return None
        return await fz.evaluate(case, self.ref.feasibility, self.ref.rates or {}, self.clock.now().year,
                                 self.feasibility)  # fmt: skip


def _freshness(assessments: dict[str, Assessment], case: CaseFile, plan: ResearchPlan) -> dict[str, Assessment]:
    """A car's data is fresh when it has a version and the plan researches nothing for it."""
    planned = {j.car_key for j in plan.jobs}
    out: dict[str, Assessment] = {}
    for key, a in assessments.items():
        fresh = bool(case.car(key).variant_id) and key not in planned
        out[key] = a.model_copy(update={"state": a.state.model_copy(update={"data_fresh": fresh})})
    return out
