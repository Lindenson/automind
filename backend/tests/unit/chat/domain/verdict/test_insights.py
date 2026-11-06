"""Deterministic insights (spec 004 FR-003, FR-009, FR-013; US3)."""

from __future__ import annotations

import time

from automind.chat.domain.verdict import insights as ins
from automind.shared.infrastructure.config.loader import load_yaml

RULES = ins.rules_from_config(load_yaml("insights.yaml"))
PROFILE = ins.Profile(weights={"efficiency": 3, "purchase_price": 2, "practicality": 1}, annual_km=15000)


def car(cid: str, **values: float) -> ins.CarValues:
    return ins.CarValues(cid, cid.upper(), values, energy_eur_per_unit=1.60)


RAV4 = car("rav4", boot_volume=580, consumption=5.6, official_price_es=45_900, accel_0_100=8.4)
CX5 = car("cx5", boot_volume=583, consumption=6.4, official_price_es=35_500, accel_0_100=10.1)
CRV = car("crv", boot_volume=587, consumption=6.3, official_price_es=44_600, accel_0_100=9.4)


def test_three_litres_of_boot_is_about_the_same() -> None:
    s = ins.build([RAV4, CX5, CRV], PROFILE, RULES)
    boot = s.get("boot_volume")
    assert boot is not None and not boot.meaningful and boot.better_car is None
    assert "boot_volume" in s.ties


def test_consumption_difference_is_meaningful_and_in_money() -> None:
    s = ins.build([RAV4, CX5], PROFILE, RULES)
    c = s.get("consumption")
    assert c is not None and c.meaningful and c.better_car == "rav4"
    assert c.diff == 0.8 and c.money_per_year == round(0.8 * 1.60 * 150)  # €192 a year at 15,000 km


def test_relevance_follows_the_priorities() -> None:
    s = ins.build([RAV4, CX5], PROFILE, RULES)
    order = [i.id for i in s.meaningful()]
    assert order.index("consumption") < order.index("accel_0_100")  # efficiency is a priority, performance not


def test_price_vs_running_cost_trade_off_has_no_payback_without_depreciation() -> None:
    """Chat 5821ac77: running costs alone never give a payback (the value each car loses is unknown here)."""
    s = ins.build([RAV4, CX5], PROFILE, RULES)
    t = next(t for t in s.trade_offs if t.cost == "official_price_es")
    assert t.gain_car == "rav4" and t.cost_car == "cx5"
    assert t.break_even_years is None and not t.no_payback


def _curve(first: float, per_year: float) -> tuple[float, ...]:
    return tuple(first + per_year * t for t in range(1, 16))


def test_payback_is_counted_on_total_cost_with_depreciation() -> None:
    rav4 = ins.CarValues("rav4", "RAV4", RAV4.values, energy_eur_per_unit=1.60, cost_curve=_curve(4000, 1000))
    cx5 = ins.CarValues("cx5", "CX5", CX5.values, energy_eur_per_unit=1.60, cost_curve=_curve(0, 1800))
    t = next(t for t in ins.build([rav4, cx5], PROFILE, RULES).trade_offs if t.gain_car == "rav4")
    assert t.break_even_years == 5.0 and not t.no_payback  # 4,000 extra at first / 800 a year


# Chat 5821ac77: Toyota Land Cruiser Prado J150 2016 (used) vs Kia Sorento MQ4 PHEV (new), 5 years, 15,000 km/year.
PRADO = ins.CarValues("prado", "Toyota Land Cruiser Prado", {"official_price_es": 30_000, "tco_per_year": 4_907,
                                                           "tco_period": 29_406},
                      cost_curve=tuple(4_907 * t + 974 * t for t in range(1, 16)))  # fmt: skip
SORENTO = ins.CarValues("sorento", "Kia Sorento", {"official_price_es": 52_000, "tco_per_year": 1_281,
                                                   "tco_period": 31_738},
                        cost_curve=tuple(1_281 * t + 5_066.6 * t for t in range(1, 16)))  # fmt: skip
OWNER = ins.Profile(weights={"ownership_cost": 5, "reliability": 3}, annual_km=15000, years=5)


def test_lower_running_costs_are_no_saving_when_the_period_total_is_higher() -> None:
    s = ins.build([PRADO, SORENTO], OWNER, RULES)
    period = s.get("tco_period")
    assert period is not None and period.meaningful and period.better_car == "prado"
    assert period.worse_car == "sorento" and period.diff == 2_332
    run = s.get("tco_per_year")
    assert run is not None and run.criterion is None  # running costs: a secondary figure, not the ownership cost
    t = s.trade_offs[0]
    # the Sorento is cheaper to run, but its total with depreciation is higher: it never pays back
    assert (t.gain, t.cost, t.gain_car, t.cost_car) == ("tco_per_year", "tco_period", "sorento", "prado")
    assert t.no_payback and t.break_even_years is None and t.period_loser == "sorento"


def test_shared_lead_has_no_single_winner() -> None:
    a, b, c = car("a", official_price_es=30_000), car("b", official_price_es=30_500), car("c", official_price_es=40_000)
    p = ins.build([a, b, c], PROFILE, RULES).get("official_price_es")
    assert p is not None and p.meaningful and p.better_car is None and p.tiers[0] == ("a", "b")
    assert p.worse_car == "c"


def test_same_input_same_output_and_fast() -> None:
    t0 = time.perf_counter()
    first = ins.build([RAV4, CX5, CRV], PROFILE, RULES)
    assert time.perf_counter() - t0 < 0.1  # SC-007 / plan: insights under 100 ms
    assert ins.build([CRV, RAV4, CX5], PROFILE, RULES) == first


def test_one_car_gives_no_comparison() -> None:
    s = ins.build([RAV4], PROFILE, RULES)
    assert s.single and not s.insights
