"""Criteria dictionary and deterministic scoring (FR-025..FR-029; research R7)."""

from pathlib import Path

import pytest
import yaml

from automind.domain.casefile import CaseDelta, CaseFile, PersonaChange, PriorityChange, apply, set_weights
from automind.domain.criteria import CriteriaModel, ReliabilitySummary, ReviewSummary, score, weights_for
from automind.domain.metrics import CarFacts

MODEL = CriteriaModel.from_config(yaml.safe_load((Path(__file__).parents[3] / "config" / "criteria.yaml").read_text()))


def case(persona="UNKNOWN", priorities=()):
    c, _ = apply(CaseFile(), CaseDelta(set_persona=PersonaChange(persona=persona)), current_year=2026)
    for key, strength in priorities:
        c, _ = apply(c, CaseDelta(add_priorities=[PriorityChange(criterion=key, strength=strength)]), current_year=2026)
    return c


@pytest.mark.parametrize(
    ("persona", "expected"),
    [
        (
            "PERFORMANCE",
            {"performance": 35, "driving_fun": 30, "traction_all_weather": 15, "ownership_cost": 10, "reliability": 10},
        ),
        ("BUYER", {"reliability": 30, "ownership_cost": 25, "practicality": 20, "comfort": 15, "efficiency": 10}),
        ("EXPERT", {"engineering": 35, "performance": 20, "reliability": 20, "driving_fun": 15, "efficiency": 10}),
    ],
)
def test_persona_default_weights(persona, expected):
    assert weights_for(case(persona), MODEL) == pytest.approx(expected)


def test_unknown_persona_is_balanced_and_sums_to_100():
    w = weights_for(case(), MODEL)
    assert abs(sum(w.values()) - 100) < 0.01 and max(w.values()) <= 20


def test_wish_strength_adds_points_then_normalizes():
    w = weights_for(case("BUYER", [("status", "HIGH")]), MODEL)
    assert w["status"] == pytest.approx(30 / 130 * 100, abs=0.01)
    assert w["reliability"] == pytest.approx(30 / 130 * 100, abs=0.01)
    w2 = weights_for(case("BUYER", [("reliability", "LOW")]), MODEL)
    assert w2["reliability"] == pytest.approx(40 / 110 * 100, abs=0.01)
    assert abs(sum(w2.values()) - 100) < 0.01


def test_user_override_wins():
    c = set_weights(case("BUYER"), {"status": 1, "reliability": 1})
    assert weights_for(c, MODEL) == {"status": 50.0, "reliability": 50.0}


def gti(**kw) -> CarFacts:
    base = dict(
        car_id="gti",
        label="Golf GTI",
        powertrain="ICE",
        power_kw=180,
        torque_nm=370,
        mass_kg=1430,
        displacement_cc=1984,
        drivetrain="FWD",
        consumption=7.0,
        energy_eur_per_100km=9.5,  # spec 006: efficiency is scored on the energy cost per 100 km
        boot_l=374,
        seats=5,
        price_eur=47500,
        sim_0_100=6.4,
        sim_400m=14.7,
    )
    return CarFacts(**{**base, **kw})


def test_scales_are_deterministic_and_clamped():
    a = score([gti()], {"performance": 50, "efficiency": 50}, MODEL)
    b = score([gti()], {"performance": 50, "efficiency": 50}, MODEL)
    assert a == b
    perf = a.cars[0].parts["performance"]
    assert 0 <= perf.score <= 100 and perf.inputs  # inputs are named
    eff = a.cars[0].parts["efficiency"].score
    assert eff == pytest.approx(50.0)  # €9.50 per 100 km on the €16 → €3 scale


def test_status_uses_three_indicators_and_age():
    new = gti(vehicle_class="compact", brand_positioning="MAINSTREAM")
    old = gti(vehicle_class="compact", brand_positioning="MAINSTREAM", condition="USED", age_years=10)
    s_new = score([new], {"status": 100}, MODEL).cars[0].parts["status"]
    s_old = score([old], {"status": 100}, MODEL).cars[0].parts["status"]
    assert s_new.score > s_old.score
    assert any("brand positioning" in i for i in s_new.inputs) and any("price" in i for i in s_new.inputs)
    only_price = score([gti()], {"status": 100}, MODEL).cars[0].parts["status"]
    assert only_price.insufficient and only_price.score is None  # needs two of three indicators


def test_review_balance_uses_only_recurring_points():
    rs = ReviewSummary(minimum_met=True, recurring={"comfort": (0, 2)}, isolated={"comfort": (5, 0)})
    part = score([gti(reviews=rs)], {"comfort": 100}, MODEL).cars[0].parts["comfort"]
    assert part.score == 0.0  # 2 recurring cons, isolated pros ignored
    weak = ReviewSummary(minimum_met=False, recurring={"comfort": (3, 0)})
    assert score([gti(reviews=weak)], {"comfort": 100}, MODEL).cars[0].parts["comfort"].insufficient


def test_reliability_score_from_documented_issues():
    clean = ReliabilitySummary(minimum_met=True, recurring=0, isolated=0, high=0)
    bad = ReliabilitySummary(minimum_met=True, recurring=2, isolated=1, high=1)
    r1 = score([gti(reliability=clean)], {"reliability": 100}, MODEL).cars[0].parts["reliability"].score
    r2 = score([gti(reliability=bad)], {"reliability": 100}, MODEL).cars[0].parts["reliability"].score
    assert r1 == 85 and r2 == 85 - 24 - 1 - 8
    many = ReliabilitySummary(minimum_met=True, recurring=0, isolated=20, high=1)  # a well-researched car
    r3 = score([gti(reliability=many)], {"reliability": 100}, MODEL).cars[0].parts["reliability"].score
    assert r3 == 85 - 8 - 8  # isolated mentions are capped: more research must not mean a worse score
    none = score([gti()], {"reliability": 100}, MODEL).cars[0].parts["reliability"]
    assert none.insufficient and none.score is None


def test_missing_data_is_insufficient_and_low_coverage_is_not_ranked():
    thin = CarFacts(car_id="thin", label="Thin", powertrain="ICE", power_kw=150)
    r = score([gti(), thin], {"performance": 40, "efficiency": 30, "practicality": 30}, MODEL)
    by = {c.car_id: c for c in r.cars}
    assert by["thin"].parts["efficiency"].insufficient and by["thin"].coverage < 0.6
    # ranking uses only criteria every car has: here too little in common → no totals, no winner
    assert r.common == [] and r.winner_car_id is None and by["gti"].total is None


def test_efficiency_compares_powertrains_on_one_scale():
    """Spec 006 FR-023: a BEV, a plug-in and a petrol car on € per 100 km; no figure → not compared for anyone."""
    cars = [gti(car_id="ice", energy_eur_per_100km=12.8), gti(car_id="bev", powertrain="BEV", energy_eur_per_100km=4.1),
            gti(car_id="phev", powertrain="PHEV", energy_eur_per_100km=7.3)]  # fmt: skip
    r = score(cars, {"efficiency": 100}, MODEL)
    eff = {c.car_id: c.parts["efficiency"].score for c in r.cars}
    assert eff["bev"] > eff["phev"] > eff["ice"]
    r2 = score(
        [*cars[:2], gti(car_id="none", energy_eur_per_100km=None)], {"efficiency": 50, "practicality": 50}, MODEL
    )
    assert "efficiency" not in r2.common


def test_a_missing_criterion_does_not_help_a_car():
    """User report: the car with no performance data won because its weight moved to its strong points."""
    full = gti(car_id="full")
    gap = CarFacts(
        car_id="gap", label="Gap", powertrain="ICE", boot_l=600, seats=5, consumption=5.0, energy_eur_per_100km=7.0
    )
    r = score([full, gap], {"performance": 15, "practicality": 45, "efficiency": 40}, MODEL)
    assert "performance" not in r.common and set(r.common) == {"practicality", "efficiency"}
    by = {c.car_id: c for c in r.cars}
    assert by["gap"].parts["performance"].insufficient and by["full"].parts["performance"].score is not None


def test_single_car_profile_is_absolute_without_ranking():
    r = score([gti()], {"performance": 50, "efficiency": 50}, MODEL)
    assert r.winner_car_id is None and not r.cars[0].ranked and r.cars[0].total is not None


def test_close_totals_are_a_tie_not_a_win():
    r = score([gti(car_id="b"), gti(car_id="a")], {"performance": 100}, MODEL)
    assert r.tie and r.winner_car_id is None
