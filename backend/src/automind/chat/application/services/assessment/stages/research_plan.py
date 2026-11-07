"""The case-driven research plan (spec 004, 006 US5, 010 FR-022): which car × area jobs to run, from the person's
persona, criteria and depth, and what earlier research left. Pure: the history is read by the service."""

from __future__ import annotations

from datetime import datetime

from automind.chat.application.services.assessment.contracts import PlanHistory, PlanRequest
from automind.chat.domain.case import CaseFile
from automind.shared.contracts.json import JsonObject
from automind.shared.research_order import plan as research_plan

PLANNED = ("CONFIRMED", "AUTO_OK", "PROPOSED")  # resolutions whose version is researched
ELECTRIFIED = ("BEV", "PHEV", "EREV")  # the market's incentives matter (spec 006 US5)


def variants_to_plan(case: CaseFile) -> list[str]:
    """The catalogue versions the plan may research: those of the cars with a settled or proposed version."""
    return [x.variant_id for x in case.cars if x.variant_id and x.resolution in PLANNED]


def research_plan_for(req: PlanRequest, history: PlanHistory, now: datetime,
                      registry: JsonObject) -> research_plan.ResearchPlan:  # fmt: skip
    """The jobs and the gap rounds for the case. A market-level area (incentives) gets the market's date for every
    car. `research_more` retries the areas below their minimum (or the named `areas`) for the focused cars, deeper."""
    case = req.case
    cars = [
        research_plan.CarToPlan(key=x.key, variant_id=x.variant_id, condition=x.condition, age_years=x.age_years,
                                electrified=(history.powertrains.get(x.variant_id) or "").upper() in ELECTRIFIED)
        for x in case.cars
        if x.variant_id and x.resolution in PLANNED
    ]  # fmt: skip
    criteria = [p.criterion for p in case.priorities] + [k for k, w in case.weights.items() if w > 0]
    days = int(registry.get("unmet_registry_retry_days", research_plan.REGISTRY_RETRY_DAYS))
    return research_plan.plan(
        cars, persona=case.persona, criteria=criteria, depth="DEEP" if req.research_more else case.depth,
        last_done=_last_done(cars, history), now=now, budget_used=_budget_used(case),
        force=_forced(req, cars, history) if req.research_more else {}, unmet=history.unmet,
        registry_done=history.registry_done, registry_days=days,
    )  # fmt: skip


def _last_done(cars: list[research_plan.CarToPlan], history: PlanHistory) -> dict[str, dict[str, datetime]]:
    """When each area was last researched; incentives are a market's area: the market's date for every car."""
    last = {vid: dict(areas) for vid, areas in history.last_done.items()}
    for x in cars:
        last.setdefault(x.variant_id, {}).pop("incentives", None)
        if history.market_done is not None:
            last[x.variant_id]["incentives"] = history.market_done
    return last


def _budget_used(case: CaseFile) -> bool:
    """A budget that covers a used car: used prices are researched."""
    return bool(case.budget.max_eur) and (
        case.budget.intent in ("USED", "ANY") or any(x.condition == "USED" for x in case.cars)
    )


def _forced(req: PlanRequest, cars: list[research_plan.CarToPlan], history: PlanHistory) -> dict[str, set[str]]:
    """The areas to research now for the focused cars: the named ones even if met, else those below the minimum."""
    keys = set(req.focus) or {x.key for x in cars}
    wanted = set(req.areas)
    return {x.variant_id: (wanted or history.unmet.get(x.variant_id, set())) for x in cars if x.key in keys}
