"""Feasibility of the user's constraints (spec 003 FR-019..FR-023, SC-007/SC-007a; research R11). Pure."""

import yaml

from automind.chat.domain.assessment.feasibility import CarFacts, Fact, Needs, UsedRange, evaluate, fingerprint
from automind.shared.infrastructure.config.loader import config_dir

RULES = yaml.safe_load((config_dir() / "feasibility.yaml").read_text(encoding="utf-8"))
YEAR = 2026


def car(**kw):
    base = dict(key="car#1", label="Toyota Land Cruiser J300", condition="NEW", vehicle_class="premium_suv_4x4",
                price=Fact(95000, "SOURCED", ["https://www.toyota.es/lc"]))  # fmt: skip
    return CarFacts(**{**base, **kw})


def checks(results, key="car#1"):
    return {c.check: c for r in results if r.car_key == key for c in r.checks}


def test_new_car_within_budget_fits():
    r = checks(evaluate(Needs(budget_eur=100000, intent="NEW"), [car()], RULES, YEAR))
    assert r["BUDGET"].verdict == "FITS"


def test_new_car_over_budget_with_new_intent_does_not_fit_and_names_numbers():
    r = checks(evaluate(Needs(budget_eur=25000, intent="NEW"), [car()], RULES, YEAR))["BUDGET"]
    assert r.verdict == "DOES_NOT_FIT"
    assert {n.label for n in r.compared} == {"official price", "your budget"}
    assert "95,000" in r.summary and "25,000" in r.summary


def test_over_budget_with_any_intent_is_used_only_from_the_depreciation_curve():
    r = checks(evaluate(Needs(budget_eur=50000, intent="ANY"), [car()], RULES, YEAR))["BUDGET"]
    assert r.verdict == "USED_ONLY" and r.used_age is not None
    assert r.used_age.basis == "ASSUMPTION"
    # premium_suv_4x4: 95,000 × 0.50 (5 y) = 47,500 ≤ 50,000; 3 y = 59,850 > 50,000 → first fitting age 4–5 y
    assert 4 <= r.used_age.from_years <= 5 and r.used_age.to_years == r.used_age.from_years + 3
    assert any(n.basis == "ASSUMPTION" for n in r.compared)


def test_editorial_range_decides_and_both_are_shown_when_they_disagree():
    ranges = [UsedRange(2018, 2019, 30000, 42000, "https://www.autopista.es/guia-usados", None),
              UsedRange(2021, 2022, 55000, 70000, "https://www.autopista.es/guia-usados", None)]  # fmt: skip
    r = checks(evaluate(Needs(budget_eur=45000, intent="USED"), [car(used_ranges=ranges)], RULES, YEAR))["BUDGET"]
    assert r.verdict == "USED_ONLY" and r.used_age.basis == "EDITORIAL"
    assert (r.used_age.from_years, r.used_age.to_years) == (YEAR - 2019, YEAR - 2018)
    assert any(n.basis == "ASSUMPTION" for n in r.compared) and any(n.sources for n in r.compared)


def test_too_old_even_for_used_does_not_fit():
    r = checks(evaluate(Needs(budget_eur=5000, intent="ANY"), [car()], RULES, YEAR))["BUDGET"]
    assert r.verdict == "DOES_NOT_FIT" and "older" in r.summary.lower()


def test_used_car_compared_at_its_age():
    used = car(condition="USED", age_years=10)
    r = checks(evaluate(Needs(budget_eur=35000, intent="USED"), [used], RULES, YEAR))["BUDGET"]
    assert r.verdict == "FITS"  # 95,000 × ~0.29 at 10 y ≈ 27,500


def test_no_price_is_unknown_with_missing_data():
    r = checks(evaluate(Needs(budget_eur=25000, intent="NEW"), [car(price=None)], RULES, YEAR))["BUDGET"]
    assert r.verdict == "UNKNOWN" and r.missing == ["official price"]


def test_monthly_budget_and_currency():
    n = Needs(budget_eur=None, budget_amount=1000, budget_currency="GBP", budget_kind="MONTHLY", intent="NEW")
    r = checks(evaluate(n, [car()], RULES, YEAR))["BUDGET"]
    # £1,000 × 1.17 × 48 months ≈ €56,160 < €95,000
    assert r.verdict == "DOES_NOT_FIT" and any(n.basis == "ASSUMPTION" and n.label == "your budget" for n in r.compared)


def test_running_cost_limit():
    tco = Fact(3600, "ASSUMPTION", [], ["15,000 km/year", "diesel €1.55/l"])
    ok = checks(evaluate(Needs(running_month_eur=400), [car(tco_annual=tco)], RULES, YEAR))["RUNNING_COST"]
    assert ok.verdict == "FITS"
    bad = checks(evaluate(Needs(running_month_eur=150), [car(tco_annual=tco)], RULES, YEAR))["RUNNING_COST"]
    assert bad.verdict == "DOES_NOT_FIT" and "300" in bad.summary and "150" in bad.summary
    assert bad.compared[0].inputs == ["15,000 km/year", "diesel €1.55/l"]


def test_space_for_passengers_and_luggage():
    small = car(
        label="Fiat 500", vehicle_class="small", seats=Fact(4, "SOURCED", ["s"]), boot_l=Fact(185, "SOURCED", ["s"])
    )
    r = checks(evaluate(Needs(passengers=4, luggage="HIGH"), [small], RULES, YEAR))["USAGE_SPACE"]
    assert r.verdict == "DOES_NOT_FIT" and "185" in r.summary
    r5 = checks(evaluate(Needs(passengers=5), [small], RULES, YEAR))["USAGE_SPACE"]
    assert r5.verdict == "DOES_NOT_FIT" and "4 seats" in r5.summary


def test_power_for_mountains_and_towing():
    weak = car(power_kw=Fact(51, "SOURCED", ["s"]), mass_kg=Fact(980, "SOURCED", ["s"]))  # 52 kW/t
    assert checks(evaluate(Needs(mountains=True), [weak], RULES, YEAR))["USAGE_POWER"].verdict == "DOES_NOT_FIT"
    strong = car(power_kw=Fact(150, "SOURCED", ["s"]), mass_kg=Fact(1600, "SOURCED", ["s"]))  # 94 kW/t
    assert (
        checks(evaluate(Needs(mountains=True, towing_kg=1500), [strong], RULES, YEAR))["USAGE_POWER"].verdict == "FITS"
    )


def test_bev_range_for_daily_distance():
    bev = car(battery_kwh=Fact(40, "SOURCED", ["s"]), consumption=Fact(16, "SOURCED", ["s"]))  # 250 km
    assert checks(evaluate(Needs(daily_km=180), [bev], RULES, YEAR))["USAGE_RANGE"].verdict == "DOES_NOT_FIT"
    assert checks(evaluate(Needs(daily_km=100), [bev], RULES, YEAR))["USAGE_RANGE"].verdict == "FITS"


def test_missing_data_makes_usage_unknown_and_no_constraints_no_checks():
    r = checks(evaluate(Needs(passengers=4), [car()], RULES, YEAR))["USAGE_SPACE"]
    assert r.verdict == "UNKNOWN" and "seats" in r.missing
    assert evaluate(Needs(), [car()], RULES, YEAR)[0].checks == []


def test_fingerprint_only_for_problems_and_stable():
    ok = evaluate(Needs(budget_eur=100000, intent="NEW"), [car()], RULES, YEAR)
    assert fingerprint(Needs(budget_eur=100000, intent="NEW"), ok) is None
    bad = evaluate(Needs(budget_eur=25000, intent="NEW"), [car()], RULES, YEAR)
    f1 = fingerprint(Needs(budget_eur=25000, intent="NEW"), bad)
    assert f1 and f1 == fingerprint(Needs(budget_eur=25000, intent="NEW"), bad)
    assert f1 != fingerprint(Needs(budget_eur=20000, intent="NEW"), bad)


def test_range_limits_only_a_bev():
    """Golden g11: a plug-in with a battery and no kWh figure was "consumption is not known" for 40 km a day."""
    phev = car(powertrain="PHEV", battery_kwh=Fact(13.8, "SOURCED"))
    assert "USAGE_RANGE" not in checks(evaluate(Needs(daily_km=40), [phev], RULES, YEAR))
    bev = car(powertrain="BEV", range_wltp=Fact(270, "SOURCED"))
    r = checks(evaluate(Needs(daily_km=100), [bev], RULES, YEAR))["USAGE_RANGE"]
    assert r.verdict == "FITS" and "WLTP range ÷ 1.2" in r.compared[0].inputs
