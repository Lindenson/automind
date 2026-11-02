"""Ownership cost (FR-033..FR-035; research R9): itemized, labelled, two-part used-car reserve."""

from pathlib import Path

import pytest
import yaml

from automind.domain.tco import BigTicket, MaintenanceSched, TcoCar, TcoRates, compute

RATES = TcoRates.from_config(yaml.safe_load((Path(__file__).parents[3] / "config" / "rates.yaml").read_text()))


def car(**kw) -> TcoCar:
    base = dict(car_id="c", label="Car", powertrain="ICE", fuel="petrol", consumption=7.0, vehicle_class="compact")
    return TcoCar(**{**base, **kw})


def items(est):
    return {i.kind: i for i in est.items}


def test_item_kinds_and_labels_for_a_new_car():
    est = compute(car(), RATES)
    kinds = items(est)
    assert set(kinds) == {"MAINTENANCE", "ENERGY", "TYRES", "ROAD_TAX"}
    assert all(i.basis in ("SOURCED", "ASSUMPTION") and i.inputs for i in est.items)
    assert est.annual_total == pytest.approx(sum(i.annual_eur for i in est.items if i.annual_eur is not None))
    assert est.five_year_total == pytest.approx(est.annual_total * 5, rel=1e-6)


def test_energy_from_consumption_and_price():
    e = items(compute(car(consumption=7.0, fuel="petrol"), RATES))["ENERGY"]
    assert e.annual_eur == pytest.approx(7.0 * 15000 / 100 * 1.60)
    d = items(compute(car(consumption=6.0, fuel="diesel"), RATES))["ENERGY"]
    assert d.annual_eur == pytest.approx(6.0 * 150 * 1.50)
    ev = items(compute(car(powertrain="BEV", fuel=None, consumption=16.0), RATES))["ENERGY"]
    assert ev.annual_eur == pytest.approx(16.0 * 150 * 0.25) and any("kWh" in i for i in ev.inputs)
    none = items(compute(car(consumption=None), RATES))["ENERGY"]
    assert none.annual_eur is None and "not included" in none.label


def test_maintenance_sourced_cost_vs_labour_assumption():
    sourced = MaintenanceSched(item="annual service", interval_km=15000, interval_months=12, cost_eur=320.0)
    m = items(compute(car(maintenance=[sourced]), RATES))["MAINTENANCE"]
    assert m.basis == "SOURCED" and m.annual_eur == pytest.approx(320.0)
    no_cost = MaintenanceSched(item="annual service", interval_km=30000, interval_months=24)
    m2 = items(compute(car(maintenance=[no_cost]), RATES))["MAINTENANCE"]
    assert m2.basis == "ASSUMPTION" and m2.annual_eur == pytest.approx((2.0 * 75 + 110) * 0.5)
    assert any("labour" in i for i in m2.inputs) and any("sourced" in i for i in m2.inputs)


def test_tyres_by_class_and_life():
    t = items(compute(car(vehicle_class="premium_suv_4x4"), RATES))["TYRES"]
    assert t.annual_eur == pytest.approx(1000 * 15000 / 30000) and t.basis == "ASSUMPTION"


def test_road_tax_only_if_a_rate_is_found():
    rt = items(compute(car(fiscal_hp=12), RATES))["ROAD_TAX"]
    assert rt.annual_eur is None and "not included" in rt.label
    sourced = items(compute(car(road_tax_eur=110.0), RATES))["ROAD_TAX"]
    assert sourced.annual_eur == 110.0 and sourced.basis == "SOURCED"


def test_used_car_two_part_reserve():
    belt = BigTicket(component="timing belt", age_from=10, age_to=12, cost_eur=650.0, evidence_ids=["e1"])
    rust = BigTicket(
        component="frame corrosion", age_from=15, age_to=20, evidence_ids=["e2"]
    )  # outside 10..15? overlaps
    late = BigTicket(component="injectors", mileage_from=400_000, mileage_to=500_000, evidence_ids=["e3"])
    est = compute(
        car(
            condition="USED",
            age_years=10,
            mileage_km=160_000,
            vehicle_class="premium_suv_4x4",
            big_tickets=[belt, rust, late],
        ),
        RATES,
    )
    big = [i for i in est.items if i.kind == "BIG_TICKET"]
    labels = {i.label for i in big}
    assert any("timing belt" in x for x in labels) and any("frame corrosion" in x for x in labels)
    assert not any("injectors" in x for x in labels)
    belt_item = next(i for i in big if "timing belt" in i.label)
    assert belt_item.basis == "SOURCED" and belt_item.five_year_eur == 650.0 and belt_item.evidence_ids == ["e1"]
    rust_item = next(i for i in big if "corrosion" in i.label)
    assert rust_item.basis == "ASSUMPTION" and rust_item.five_year_eur == 900
    reserve = items(est)["BASE_RESERVE"]
    assert reserve.basis == "ASSUMPTION" and reserve.annual_eur == 1300  # 10–14 years × premium/SUV/4x4


def test_new_car_has_no_reserve():
    assert not any(i.kind in ("BIG_TICKET", "BASE_RESERVE") for i in compute(car(), RATES).items)


def test_annual_km_override_and_rate_overrides():
    a = items(compute(car(), RATES, annual_km=30000))["ENERGY"].annual_eur
    assert a == pytest.approx(7.0 * 300 * 1.60)
    cheap = TcoRates.from_config(
        yaml.safe_load((Path(__file__).parents[3] / "config" / "rates.yaml").read_text()),
        overrides={"fuel_eur_per_l": 1.0},
    )
    assert items(compute(car(), cheap))["ENERGY"].annual_eur == pytest.approx(7.0 * 150 * 1.0)
