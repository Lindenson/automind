"""Policy additions for spec 003 US3 (T040): budget-intent question, FEASIBILITY before REPORT."""

from automind.domain.casefile import Budget, CaseCar, CaseDelta, CaseFile, Needs, RunningLimit, apply
from automind.domain.policy import CarState, decide, fingerprint
from automind.domain.research_plan import CarToPlan, plan

FRESH = CarState(in_catalog=True, data_fresh=True)


def case(**kw):
    car = CaseCar(key="car#1", request_text="Golf", make="VW", model="Golf", variant_id="v1", resolution="CONFIRMED",
                  condition=kw.pop("condition", "NEW"))  # fmt: skip
    return CaseFile(cars=[car], **kw)


def test_budget_with_unknown_intent_and_unknown_condition_asks_once():
    c = case(condition="UNKNOWN", budget=Budget(max_eur=20000))
    a = decide(c, "compare", {"car#1": FRESH}, cost_estimate_eur=0, last_fingerprint=None)
    assert a.kind == "ASK" and "BUDGET_INTENT" in a.questions
    c.asked.append("BUDGET_INTENT")
    assert decide(c, "compare", {"car#1": FRESH}, cost_estimate_eur=0, last_fingerprint=None).kind == "REPORT"


def test_explicit_new_or_intent_known_does_not_ask():
    for c in (case(condition="NEW", budget=Budget(max_eur=20000)),
              case(condition="UNKNOWN", budget=Budget(max_eur=20000, intent="ANY"))):  # fmt: skip
        assert decide(c, "compare", {"car#1": FRESH}, cost_estimate_eur=0, last_fingerprint=None).kind == "REPORT"


def test_feasibility_pending_comes_before_report_and_follow_ups():
    c = case(budget=Budget(max_eur=20000, intent="NEW"))
    for req in ("compare", "single", "follow_up_question"):
        a = decide(c, req, {"car#1": FRESH}, cost_estimate_eur=0, last_fingerprint=None, feasibility_pending=True)
        assert a.kind == "FEASIBILITY"
    a = decide(c, "compare", {"car#1": FRESH}, cost_estimate_eur=0, last_fingerprint=None, feasibility_pending=False)
    assert a.kind == "REPORT"


def test_research_still_comes_first():
    c = case(budget=Budget(max_eur=20000, intent="NEW"))
    stale = CarState(in_catalog=True, data_fresh=False)
    a = decide(c, "compare", {"car#1": stale}, cost_estimate_eur=0.1, last_fingerprint=None, feasibility_pending=True)
    assert a.kind == "RESEARCH"


def test_constraints_change_the_fingerprint_and_merge_partially():
    c = case()
    f0 = fingerprint(c)
    c2, log = apply(c, CaseDelta(set_budget=Budget(max_eur=30000)), current_year=2026)
    assert fingerprint(c2) != f0 and any("budget" in x for x in log)
    c3, log = apply(c2, CaseDelta(set_budget=Budget(intent="USED")), current_year=2026)  # intent-only answer
    assert c3.budget.max_eur == 30000 and c3.budget.intent == "USED" and fingerprint(c3) != fingerprint(c2)
    c4, _ = apply(c3, CaseDelta(set_needs=Needs(passengers=4)), current_year=2026)
    c5, _ = apply(c4, CaseDelta(set_needs=Needs(luggage="HIGH")), current_year=2026)
    assert c5.needs.passengers == 4 and c5.needs.luggage == "HIGH"
    c6, log = apply(c5, CaseDelta(set_running_cost_limit=RunningLimit(amount_eur=1800, period="YEAR")),
                    current_year=2026)  # fmt: skip
    assert c6.running_cost_limit.per_month == 150 and any("running cost" in x for x in log)


def test_used_price_area_is_planned_only_when_a_budget_needs_it():
    cars = [CarToPlan("car#1", "v1", "NEW")]
    p0 = plan(
        cars, persona="BUYER", criteria=[], depth="STANDARD", last_done={}, now=__import__("datetime").datetime.now()
    )
    assert all(j.area != "used_price" for j in p0.jobs)
    p1 = plan(cars, persona="BUYER", criteria=[], depth="STANDARD", last_done={}, budget_used=True,
              now=__import__("datetime").datetime.now())  # fmt: skip
    assert any(j.area == "used_price" for j in p1.jobs)


def test_research_more_researches_and_always_reports():
    c = case()
    stale = CarState(in_catalog=True, data_fresh=False)
    assert decide(c, "research_more", {"car#1": stale}, cost_estimate_eur=0.1, last_fingerprint=None).kind == "RESEARCH"
    # after the research, even an unchanged case gets a fresh report (never "nothing new")
    a = decide(c, "research_more", {"car#1": FRESH}, cost_estimate_eur=0, last_fingerprint=fingerprint(c))
    assert a.kind == "REPORT"


def test_forced_areas_are_planned_although_fresh():
    from datetime import UTC, datetime

    now = datetime(2026, 11, 2, tzinfo=UTC)
    done = {"v1": {a: now for a in ("specs", "price", "maintenance", "reliability", "reviews")}}
    cars = [CarToPlan("car#1", "v1", "NEW")]
    assert plan(cars, persona="BUYER", criteria=[], depth="STANDARD", last_done=done, now=now).jobs == []
    p = plan(
        cars, persona="BUYER", criteria=[], depth="DEEP", last_done=done, now=now, force={"v1": {"specs", "price"}}
    )
    assert {j.area for j in p.jobs} == {"specs", "price"} and p.rounds == 2


def test_unmet_areas_are_retried_after_12_hours():
    from datetime import UTC, datetime, timedelta

    now = datetime(2026, 11, 2, 18, tzinfo=UTC)
    cars = [CarToPlan("car#1", "v1", "NEW")]
    recent = {"v1": {a: now - timedelta(hours=2) for a in ("specs", "price", "maintenance", "reliability", "reviews")}}
    older = {"v1": {a: now - timedelta(hours=13) for a in ("specs", "price", "maintenance", "reliability", "reviews")}}
    kw = dict(persona="BUYER", criteria=[], depth="STANDARD", now=now, unmet={"v1": {"specs"}})
    assert plan(cars, last_done=recent, **kw).jobs == []
    assert [j.area for j in plan(cars, last_done=older, **kw).jobs] == ["specs"]
