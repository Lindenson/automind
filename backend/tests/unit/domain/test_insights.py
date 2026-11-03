"""Deterministic insights (spec 004 FR-003, FR-009, FR-013; US3)."""

from __future__ import annotations

import time

from automind.domain import insights as ins
from automind.infrastructure.config import load_yaml

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


def test_price_vs_running_cost_trade_off_has_a_break_even() -> None:
    s = ins.build([RAV4, CX5], PROFILE, RULES)
    t = next(t for t in s.trade_offs if t.cost == "official_price_es")
    assert t.gain_car == "rav4" and t.cost_car == "cx5"
    assert t.break_even_years == round(10_400 / 192, 1)


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
