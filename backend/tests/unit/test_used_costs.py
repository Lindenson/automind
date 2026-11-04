"""Spec 008 US4: a used car is costed and scored as used — assumed age never 0, the used price as the purchase
price (never the new one), depreciation from the value now, reliability with age and mileage, warranty status."""

from __future__ import annotations

from automind.domain import criteria, tco, used
from automind.domain.metrics import CarFacts, ReliabilitySummary

CURVE = {0.0: 1.0, 1.0: 0.8, 3.0: 0.62, 5.0: 0.5, 8.0: 0.36, 10.0: 0.3, 15.0: 0.18}


def test_assumed_age_from_mileage_generation_or_default_never_zero() -> None:
    assert used.assumed_age(50000, None, None, 2026) == (3, "50,000 km at ~15,000 km a year")
    assert used.assumed_age(4000, None, None, 2026)[0] == 1
    assert used.assumed_age(None, 2015, 2024, 2026)[0] == 7  # 2026 − 2019.5, rounded half up
    assert used.assumed_age(None, None, None, 2026)[0] == 5
    assert used.assumed_age(30000, None, None, 2026, km_per_year=10000)[0] == 3


def test_used_price_for_the_year() -> None:
    rs = [
        used.UsedRange(18000, 22000, 2019, 2020, "a"),
        used.UsedRange(24000, 28000, 2022, 2023, "b"),
        used.UsedRange(10000, 40000, None, None, "c"),
    ]
    p = used.used_price_for(rs, 2023)
    assert p is not None and p.eur == 26000 and p.exact_year and p.url == "b"
    near = used.used_price_for(rs, 2021)  # one year from 2020 and from 2022: the nearest range, not exact
    assert near is not None and not near.exact_year
    assert used.used_price_for(rs, 2010) is not None and used.used_price_for(rs, 2010).url == "c"  # type: ignore[union-attr]
    assert used.used_price_for([], 2023) is None


def test_warranty_remaining_or_expired() -> None:
    assert used.warranty_status(2023, 3, 2026) == used.Warranty("REMAINING", 2026, 3, False)
    assert used.warranty_status(2019, 2, 2026).state == "EXPIRED"
    assert used.warranty_status(None, 3, 2026).state == "UNKNOWN"
    assert used.warranty_status(2023, None, 2026).state == "UNKNOWN"
    assert used.warranty_status(2023, 3, 2026, assumed=True).assumed


PRICE = {"lo": 60000, "hi": 15000}


def test_purchase_price_of_a_used_car_is_its_used_price_never_the_new_one() -> None:
    new = CarFacts("a", "A", "ICE", price_eur=48000)
    usedcar = CarFacts("b", "B", "ICE", price_eur=48000, condition="USED", age_years=3, used_price_eur=26000)
    nodata = CarFacts("c", "C", "ICE", price_eur=48000, condition="USED", age_years=3)
    assert criteria._price(new, PRICE)[1] == ["official price 48000 EUR"]
    score, inputs = criteria._price(usedcar, PRICE)
    assert inputs == ["used price 26000 EUR (sourced)"] and score is not None and score > criteria._price(new, PRICE)[0]  # type: ignore[operator]
    assert criteria._price(nodata, PRICE)[0] is None


REL = {
    "base_none_found": 85,
    "per_recurring": -12,
    "recurring_cap": -48,
    "per_high": -8,
    "high_cap": -24,
    "per_isolated": -1,
    "isolated_cap": -8,
    "age_free_years": 5,
    "per_year_over": -1.5,
    "age_max": -20,
    "mileage_free_km": 60000,
    "per_10k_over": -1,
    "mileage_max": -15,
}


def test_reliability_counts_age_and_mileage_of_a_used_car() -> None:
    r = ReliabilitySummary(minimum_met=True)
    fresh = criteria._reliability(
        CarFacts("a", "A", "ICE", reliability=r, condition="USED", age_years=3, mileage_km=40000), REL
    )
    worn = criteria._reliability(
        CarFacts("b", "B", "ICE", reliability=r, condition="USED", age_years=9, mileage_km=160000), REL
    )
    assert fresh[0] == 85
    assert worn[0] == 85 - 6 - 10
    assert "mileage 160,000 km" in worn[1] and "age 9 years" in worn[1]


def test_depreciation_of_a_used_car_starts_from_its_used_price() -> None:
    car = tco.TcoCar(
        "a", "A4", "ICE", condition="USED", age_years=3, price_eur=48000, used_price_eur=26000, retention_curve=CURVE
    )
    item = tco._depreciation(car, 5)
    expected = 26000 - 26000 * 0.36 / 0.62  # value share at 8 years over the share at 3
    assert abs((item.five_year_eur or 0) - expected) < 1
    assert "value now €26,000 (sourced used price, 3 years)" in item.inputs[0]


def test_a_used_car_without_a_used_price_is_valued_from_the_new_price_at_its_age_never_as_new() -> None:
    car = tco.TcoCar("a", "A4", "ICE", condition="USED", age_years=0, price_eur=48000, retention_curve=CURVE)
    item = tco._depreciation(car, 5)
    at6 = 0.5 + (0.36 - 0.5) / 3  # the class curve between 5 and 8 years
    assert abs((item.five_year_eur or 0) - 48000 * (0.8 - at6)) < 1  # from age 1 (0.8 of new), not from new
    assert any("value now" in x for x in item.inputs)
