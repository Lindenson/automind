"""Energy model per powertrain (spec 006 US1, research R1–R3, R6), with the incident pair of chat 5be54966."""

import pytest

from automind.domain import energy as en
from automind.domain import tco

RWF = {"ICE": 1.15, "MHEV": 1.15, "HEV": 1.15, "BEV": 1.2, "NEDC": 1.40}
R = en.Rates(en.Price(1.60, "l", "petrol"), en.Price(1.50, "l", "diesel"), RWF, en.EnergyConfig())
KM = 18000
BYD = en.EnergyCar("PHEV", "petrol", consumption=0.9, consumption_cs=5.3, battery_kwh=18.3, range_wltp=80)
ATECA = en.EnergyCar("ICE", "petrol", consumption=6.3)


def test_ice_unchanged():
    e = en.estimate(ATECA, R, en.UsageContext(KM))
    assert [p.energy for p in e.parts] == ["petrol"]
    assert e.annual_eur == pytest.approx(6.3 * 1.15 * 180 * 1.60, abs=3)
    assert e.label == "Energy (petrol)"


def test_mild_and_full_hybrid_get_no_electric_share():
    for pt in ("MHEV", "HEV"):
        e = en.estimate(en.EnergyCar(pt, "petrol", consumption=5.0, battery_kwh=1.4), R, en.UsageContext(KM))
        assert e.electric_share is None and [p.energy for p in e.parts] == ["petrol"]


def test_phev_splits_electric_and_fuel_never_the_weighted_figure():
    e = en.estimate(BYD, R, en.UsageContext(KM, climate="HOT"))
    assert [p.energy for p in e.parts] == ["electricity", "petrol"]
    assert 0 < e.electric_share < 1
    assert all(p.per_100km != 0.9 for p in e.parts)
    assert sum(p.km for p in e.parts) == pytest.approx(KM, abs=2)
    assert any("derived" in i for i in e.inputs)  # kWh/100 km from usable kWh ÷ WLTP range
    assert any("assumed" in i for i in e.inputs)  # home charging not stated
    assert e.alt_eur_per_100km and e.alt_eur_per_100km > e.eur_per_100km  # without home charging costs more


def test_phev_without_charge_sustaining_figure_cannot_be_computed():
    car = en.EnergyCar("PHEV", "petrol", consumption=0.9, battery_kwh=18.3, range_wltp=80)
    e = en.estimate(car, R, en.UsageContext(KM))
    assert e.missing == [en.CS_MISSING]
    assert e.annual_eur is None and e.parts == []
    assert e.label.startswith("Energy: cannot be computed — missing: fuel consumption with an empty battery")


def test_phev_share_follows_daily_distance_and_charging():
    short = en.estimate(BYD, R, en.UsageContext(KM, daily_km=30, home_charging="YES"))
    long_ = en.estimate(BYD, R, en.UsageContext(KM, daily_km=150, home_charging="YES"))
    street = en.estimate(BYD, R, en.UsageContext(KM, daily_km=30, home_charging="NO"))
    assert short.electric_share > long_.electric_share
    assert short.electric_share > street.electric_share
    assert short.electric_share <= en.MAX_SHARE


def test_bev_wltp_gets_no_losses_display_test_gets_them_once():
    wltp = en.estimate(en.EnergyCar("BEV", consumption_ev=15.0), R, en.UsageContext(KM, home_charging="YES"))
    assert wltp.parts[0].per_100km == pytest.approx(15.0 * 1.2, abs=0.01)
    assert not any("losses" in f for f in wltp.factors)
    shown = en.estimate(en.EnergyCar("BEV", consumption_ev_real=16.0), R, en.UsageContext(KM, home_charging="YES"))
    assert shown.parts[0].per_100km > 16.0
    assert sum("losses" in f for f in shown.factors) == 1
    plug = en.estimate(en.EnergyCar("BEV", consumption_ev_real=16.0, ev_real_meter="plug"), R, en.UsageContext(KM))
    assert plug.parts[0].per_100km == 16.0


def test_bev_public_charging_costs_more_than_home():
    car = en.EnergyCar("BEV", consumption_ev=16.0)
    cfg = en.EnergyConfig(home=en.Price(0.12, "kWh", "home"))
    r = en.Rates(R.petrol, R.diesel, RWF, cfg)
    home = en.estimate(car, r, en.UsageContext(KM, home_charging="YES"))
    street = en.estimate(car, r, en.UsageContext(KM, home_charging="NO"))
    assert street.eur_per_100km > 2 * home.eur_per_100km


def test_climate_and_motorway_factors_are_named():
    car = en.EnergyCar("BEV", consumption_ev=16.0)
    south = en.estimate(car, R, en.UsageContext(KM, climate="HOT", usage=("MOTORWAY",)))
    north = en.estimate(car, R, en.UsageContext(KM, climate="MILD", usage=("CITY",)))
    assert south.eur_per_100km > north.eur_per_100km
    assert any("hot climate" in f for f in south.factors) and any("motorway" in f for f in south.factors)


def test_bev_without_consumption_names_the_input():
    e = en.estimate(en.EnergyCar("BEV"), R, en.UsageContext(KM))
    assert e.missing == [en.EV_MISSING]


def test_tco_energy_item_carries_parts_and_missing():
    rates = tco.TcoRates.from_config(
        {
            "fuel_eur_per_l": 1.6, "diesel_eur_per_l": 1.5, "electricity_eur_per_kwh": 0.25, "labour_eur_per_h": 75,
            "annual_km": 15000, "horizon_years": 5,
            "tyre_life_km": {"compact": 40000}, "tyre_set_eur": {"compact": 450},
            "service_hours": {"ICE": 2, "PHEV": 2.2}, "service_parts_eur": {"ICE": 110, "PHEV": 130},
            "default_interval_km": {"ICE": 15000, "PHEV": 15000}, "big_ticket_default_eur": 900,
            "base_reserve_eur_per_year": {"compact": [1, 2, 3, 4]}, "real_world_factor": RWF,
        },
        {"electricity_eur_per_kwh": 0.12},
    )  # fmt: skip
    assert rates.energy.home.value == 0.12 and rates.energy.home.basis == "USER"
    car = tco.TcoCar("b", "BYD", "PHEV", "petrol", consumption=0.9, consumption_cs=5.3, battery_kwh=18.3,
                     range_wltp=80, vehicle_class="compact")  # fmt: skip
    item = next(i for i in tco.compute(car, rates, KM).items if i.kind == "ENERGY")
    assert [p.energy for p in item.parts] == ["electricity", "petrol"] and item.annual_eur
    bad = tco.TcoCar("b", "BYD", "PHEV", "petrol", consumption=0.9, vehicle_class="compact")
    item = next(i for i in tco.compute(bad, rates, KM).items if i.kind == "ENERGY")
    assert item.annual_eur is None and en.CS_MISSING in item.missing


def test_a_cost_without_energy_is_named_and_not_compared():
    from automind.orchestration.nodes.compute import _checked_costs, energy_notices

    rates = tco.TcoRates.from_config(
        {
            "fuel_eur_per_l": 1.6, "diesel_eur_per_l": 1.5, "electricity_eur_per_kwh": 0.25, "labour_eur_per_h": 75,
            "annual_km": 15000, "horizon_years": 5,
            "tyre_life_km": {"compact": 40000}, "tyre_set_eur": {"compact": 450},
            "service_hours": {"ICE": 2, "PHEV": 2.2}, "service_parts_eur": {"ICE": 110, "PHEV": 130},
            "default_interval_km": {"ICE": 15000, "PHEV": 15000}, "big_ticket_default_eur": 900,
            "base_reserve_eur_per_year": {"compact": [1, 2, 3, 4]}, "real_world_factor": RWF,
        }
    )  # fmt: skip
    byd = tco.compute(tco.TcoCar("b", "BYD", "PHEV", "petrol", consumption=0.9, vehicle_class="compact"), rates, KM)
    ateca = tco.compute(tco.TcoCar("a", "Ateca", "ICE", "petrol", consumption=6.3, vehicle_class="compact"), rates, KM)
    costs = _checked_costs([byd, ateca], {}, [])
    assert set(costs) == {"a"}
    (n,) = energy_notices([byd, ateca], {"b": "BYD Seal U"}, "ru")
    assert "BYD Seal U" in n["text"] and "разряженной батареей" in n["text"] and n["level"] == "warning"


# ---- a car sold only in China: CLTC figures (chat 2026-11-06, Deepal S09 vs Li L9) ----------------------------

RWF_CN = {**RWF, "CLTC": 1.4}
R_CN = en.Rates(R.petrol, R.diesel, RWF_CN, R.cfg)
S09 = en.EnergyCar("PHEV", "petrol", consumption_cs=5.6, battery_kwh=40.18, range_cltc=220)


def test_erev_kwh_estimated_from_battery_and_cltc_range():
    e = en.estimate(S09, R_CN, en.UsageContext(KM, home_charging="YES"))
    assert not e.missing and [p.energy for p in e.parts] == ["electricity", "petrol"]
    loss = 0.85 * 0.10 + 0.15 * 0.10  # plug-in mix: home + public AC
    assert e.parts[0].per_100km == pytest.approx(40.18 / 220 * 100 * 1.4 * (1 + loss), abs=0.02)
    how = next(i for i in e.inputs if i.startswith("electricity"))
    assert "ESTIMATE" in how and "CLTC" in how and "40.18 kWh battery" in how
    assert any("losses" in f for f in e.factors)
    assert any("CLTC, China 220 km" in i for i in e.inputs)  # the real range is CLTC ÷ 1.4 too


def test_sourced_cltc_kwh_wins_over_the_battery_estimate():
    car = en.EnergyCar("PHEV", "petrol", consumption_cs=5.6, battery_kwh=40.18, range_cltc=220, consumption_ev_cltc=19)
    e = en.estimate(car, R_CN, en.UsageContext(KM, home_charging="YES"))
    assert e.parts[0].per_100km == pytest.approx(19 * 1.4, abs=0.01)
    assert not any("ESTIMATE" in i for i in e.inputs)


def test_wltp_figures_win_over_cltc():
    car = en.EnergyCar("PHEV", "petrol", consumption_cs=5.6, battery_kwh=20, range_wltp=100, range_cltc=220)
    e = en.estimate(car, R_CN, en.UsageContext(KM, home_charging="YES"))
    assert not any("CLTC" in i for i in e.inputs)


def test_erev_without_battery_names_the_missing_kwh():
    car = en.EnergyCar("PHEV", "petrol", consumption_cs=5.6, range_cltc=220)
    assert en.estimate(car, R_CN, en.UsageContext(KM)).missing == [en.EV_MISSING]
