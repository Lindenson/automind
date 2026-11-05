"""Environmental label, incentive status and break-even (spec 006 US5)."""

from datetime import date

from automind.domain import incentives as inc

TODAY = date(2026, 11, 4)


def test_env_labels():
    assert inc.env_label("PHEV", 80, "petrol", 2025).label == "ZERO"  # BYD Seal U DM-i
    assert inc.env_label("PHEV", 35, "petrol", 2025).label == "ECO"
    assert inc.env_label("PHEV", None, "petrol", 2025).label == "UNKNOWN"
    assert inc.env_label("ICE", None, "petrol", 2024).label == "C"  # SEAT Ateca 1.5 TSI
    assert inc.env_label("HEV", None, "petrol", 2024).label == "ECO"  # Toyota RAV4 hybrid
    assert inc.env_label("MHEV", None, "diesel", 2023).label == "ECO"
    assert inc.env_label("ICE", None, "diesel", 2010).label == "B"
    assert inc.env_label("ICE", None, "diesel", 2004).label == "NONE"
    assert inc.env_label("EREV", None, None, 2025).label == "ZERO"
    assert inc.env_label("ICE", None, "petrol", None).label == "UNKNOWN"


def test_incentive_status_and_what_is_deducted():
    old = inc.Incentive("subsidy.moves", "MOVES III", 4500, date(2024, 1, 1), date(2025, 12, 31), ("e1",))
    new = inc.Incentive("subsidy.next", "Plan Auto+", 3000, date(2026, 6, 1), date(2027, 12, 31), ("e2",))
    unsourced = inc.Incentive("subsidy.rumour", "Rumour", 9000, date(2026, 1, 1), date(2027, 1, 1))
    assert inc.status(old, TODAY) == "EXPIRED"
    assert inc.status(new, TODAY) == "ACTIVE"
    assert inc.status(unsourced, TODAY) == "UNKNOWN"
    assert inc.deductible([old, new, unsourced], TODAY) == 3000


def _curve(first: float, per_year: float) -> list[float]:
    """Total cost (value lost + running) after 1..15 years: a front-loaded loss, then a steady cost."""
    return [first + per_year * t for t in range(1, 16)]


def test_break_even():
    e, c = _curve(4300, 1900), _curve(0, 2900)
    b = inc.break_even(38000, 33700, 1900, 2900, ownership_years=7, curve_e=e, curve_c=c)
    assert b.verdict == "YEARS" and b.years == 4.5 and not b.beyond_ownership
    assert inc.break_even(38000, 33700, 3000, 2900, curve_e=_curve(4300, 3000), curve_c=c).verdict == "NEVER"
    assert inc.break_even(32000, 33700, 1900, 2900).verdict == "ALREADY_CHEAPER"
    assert inc.break_even(32000, 33700, 3100, 2900).verdict == "CHEAPER_TO_BUY"
    assert inc.break_even(None, 33700, 1900, 2900).verdict == "UNKNOWN"
    long = inc.break_even(48000, 33700, 1900, 2900, ownership_years=5, curve_e=_curve(14300, 1900), curve_c=c)
    assert long.years == 14.5 and long.beyond_ownership
    sub = inc.break_even(38000, 33700, 1900, 2900, subsidy_eur=3000, curve_e=e, curve_c=c)
    assert sub.years == 1.5 and "after €3,000 active subsidy" in sub.inputs[0]


def test_no_payback_from_running_costs_alone():
    """Chat 5821ac77: without the value each car loses, a dearer car's lower running cost is no payback."""
    b = inc.break_even(52000, 30000, 1281, 4907, ownership_years=5)
    assert b.verdict == "UNKNOWN" and b.years is None


def test_payback_counts_depreciation():
    """A new car losing ~€5,000 a year against a used one losing little: lower running costs do not pay back."""
    new = _curve(0, 1281 + 5000)  # running + value lost per year
    used = _curve(0, 4907 + 900)
    b = inc.break_even(52000, 30000, 1281, 4907, ownership_years=5, curve_e=new, curve_c=used)
    assert b.verdict == "NEVER" and b.years is None


def test_market_incentives_planned_once_on_the_first_electrified_car():
    from datetime import UTC, datetime

    from automind.domain import research_plan as rp

    now = datetime(2026, 11, 4, tzinfo=UTC)
    cars = [rp.CarToPlan("a", "ice", "NEW"), rp.CarToPlan("b", "bev", "NEW", electrified=True),
            rp.CarToPlan("c", "phev", "NEW", electrified=True)]  # fmt: skip
    p = rp.plan(cars, persona="BUYER", criteria=[], depth="STANDARD", last_done={}, now=now)
    assert [(j.car_key, j.area) for j in p.jobs if j.area == "incentives"] == [("b", "incentives")]
    only_ice = rp.plan(cars[:1], persona="BUYER", criteria=[], depth="STANDARD", last_done={}, now=now)
    assert not [j for j in only_ice.jobs if j.area == "incentives"]
    assert rp.minimum_met("incentives", [rp.SourceHit("idae.es", "PUBLICATION", 2)])
