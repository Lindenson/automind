"""The assessment service's plan (spec 012 S9c): the research plan from what earlier research left, its cost, a
declined plan, the cars' freshness, the warnings given once — and a research history that cannot be read fails the
turn instead of planning blind."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from automind.chat.application.ports import StoreUnavailable
from automind.chat.application.services.assessment import AssessmentService, PlanRequest
from automind.chat.application.services.assessment.contracts import PlanHistory
from automind.chat.application.services.assessment.stages.research_plan import research_plan_for
from automind.chat.application.services.assessment.stages.warnings import new_warnings
from automind.chat.application.services.identification.contracts import Assessment
from automind.chat.dialog.prompts import load_all
from automind.chat.dialog.report_wording import WORDING
from automind.chat.domain.case import CaseCar, CaseFile
from automind.chat.domain.decision import CarState
from automind.delivery.bootstrap import reference
from automind.shared.research_order.plan import ResearchPlan, Warning

REF = reference(load_all())
NOW = datetime(2026, 11, 7, tzinfo=UTC)


class _History:
    """Earlier research: nothing done, or a store that cannot be read (`down`)."""

    def __init__(self, *, down: bool = False, last: dict[str, dict[str, datetime]] | None = None) -> None:
        self.down, self.last = down, last or {}

    def _check(self) -> None:
        if self.down:
            raise StoreUnavailable("research_runs: OperationalError")

    async def powertrains(self, variant_ids: list[str]) -> dict[str, str | None]:
        self._check()
        return dict.fromkeys(variant_ids, "BEV")

    async def last_done(self, variant_ids: list[str]) -> dict[str, dict[str, datetime]]:
        self._check()
        return self.last

    async def unmet_areas(self, variant_ids: list[str]) -> dict[str, set[str]]:
        self._check()
        return {}

    async def registry_done(self, variant_ids: list[str]) -> dict[str, dict[str, datetime]]:
        self._check()
        return {}


class _Estimator:
    async def estimate(self, jobs: list[tuple[str, str]], rounds: int) -> float:
        return 0.01 * len(jobs)


class _Clock:
    def now(self) -> datetime:
        return NOW


def _case(**fields: object) -> CaseFile:
    car = CaseCar(key="a", request_text="Tesla Model 3", make="Tesla", model="Model 3", variant_id="v1",
                  resolution="CONFIRMED", condition="NEW")  # fmt: skip
    return CaseFile(cars=[car], **fields)


def _service(history: _History) -> AssessmentService:
    return AssessmentService(REF, history, _Estimator(), _Clock(), WORDING)


def _assessed() -> dict[str, Assessment]:
    return {"a": Assessment(state=CarState(data_fresh=True))}


async def test_a_car_with_research_to_do_is_not_fresh_and_priced() -> None:
    planned = await _service(_History()).plan(PlanRequest(_case(), _assessed()))
    assert planned.plan.jobs
    assert planned.assessments["a"].state.data_fresh is False
    assert planned.cost_eur == pytest.approx(0.01 * len(planned.plan.jobs))
    assert planned.declined is False and planned.feasibility is None


async def test_the_plan_the_person_declined_is_remembered_by_its_key() -> None:
    first = await _service(_History()).plan(PlanRequest(_case(), _assessed()))
    again = await _service(_History()).plan(PlanRequest(_case(declined_plan=first.plan_key), _assessed()))
    assert again.declined is True
    state = again.to_state([])
    assert state["research_plan"]["key"] == first.plan_key and "notices" not in state


async def test_a_research_history_that_cannot_be_read_fails_the_turn() -> None:
    with pytest.raises(StoreUnavailable):
        await _service(_History(down=True)).plan(PlanRequest(_case(), _assessed()))


def test_find_it_researches_the_named_area_again_even_when_fresh() -> None:
    fresh = {"v1": {area: NOW - timedelta(hours=1) for area in ("specs", "price", "reviews", "measured")}}
    history = PlanHistory(powertrains={"v1": "BEV"}, last_done=fresh, unmet={}, registry_done={}, market_done=None)
    req = PlanRequest(_case(), _assessed(), research_more=True, areas=("reviews",))
    jobs = research_plan_for(req, history, NOW, {}).jobs
    assert ("v1", "reviews") in {(j.variant_id, j.area) for j in jobs}
    assert all(j.fresh for j in jobs if j.area == "reviews")


def test_incentives_take_the_market_date_for_every_car() -> None:
    history = PlanHistory(powertrains={"v1": "BEV"}, last_done={"v1": {"incentives": NOW - timedelta(days=900)}},
                          unmet={}, registry_done={}, market_done=NOW - timedelta(hours=1))  # fmt: skip
    jobs = research_plan_for(PlanRequest(_case(), _assessed()), history, NOW, {}).jobs
    assert "incentives" not in {j.area for j in jobs}


def test_a_warning_is_given_once_a_turn() -> None:
    plan = ResearchPlan(jobs=[], rounds=0, warnings=[Warning("OLD_CAR", "a")])
    case = _case()
    first = new_warnings(plan, case, frozenset(), WORDING)
    assert [n["level"] for n in first] == ["warning"] and "older than 25 years" in first[0]["text"]
    assert new_warnings(plan, case, frozenset({first[0]["text"]}), WORDING) == []
