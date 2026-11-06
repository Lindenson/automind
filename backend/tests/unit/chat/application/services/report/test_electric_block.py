"""The electric section (spec 006 US7): same rows per car, gaps as null, a combustion car on € per 100 km."""

from types import SimpleNamespace as NS

from automind.chat.application.services.report import electric_block
from automind.chat.domain.cost import tco
from automind.chat.domain.cost.energy import UsageContext
from tests.unit.chat.domain.cost.test_energy import RWF

RATES = tco.TcoRates.from_config(
    {
        "fuel_eur_per_l": 1.78, "diesel_eur_per_l": 1.89, "electricity_eur_per_kwh": 0.17, "labour_eur_per_h": 75,
        "annual_km": 15000, "horizon_years": 5,
        "tyre_life_km": {"compact": 40000}, "tyre_set_eur": {"compact": 450},
        "service_hours": {"ICE": 2, "PHEV": 2.2}, "service_parts_eur": {"ICE": 110, "PHEV": 130},
        "default_interval_km": {"ICE": 15000, "PHEV": 15000}, "big_ticket_default_eur": 900,
        "base_reserve_eur_per_year": {"compact": [1, 2, 3, 4]}, "real_world_factor": RWF,
    }
)  # fmt: skip
USE = UsageContext(18000, climate="HOT")


def car(**vals):
    return {"values": {k: NS(available=True, value_num=v, value_text=None) for k, v in vals.items()}}


def test_electric_section_for_the_incident_pair():
    byd = tco.TcoCar("b", "BYD Seal U DM-i", "PHEV", "petrol", consumption=0.9, consumption_cs=5.3, battery_kwh=18.3,
                     range_wltp=80, vehicle_class="compact", use=USE)  # fmt: skip
    ateca = tco.TcoCar("a", "SEAT Ateca 1.5 TSI", "ICE", "petrol", consumption=6.3, vehicle_class="compact", use=USE)
    est = [tco.compute(t, RATES, 18000) for t in (byd, ateca)]
    labels = {"b": {"label": "ZERO", "rule": "plug-in ≥ 40 km: ZERO"}, "a": {"label": "C", "rule": "petrol: C"}}
    b = electric_block.build([car(charge_ac_kw=6.6), car()], [byd, ateca], est, RATES, labels, "ru")
    assert b is not None and b["title"] == "Электро" and [c["car_id"] for c in b["cars"]] == ["b"]
    v = b["cars"][0]["values"]
    assert v["battery"]["usable_kwh"] == 18.3 and v["charging_dc"]["peak_kw"] is None  # gap → null
    assert 0 < v["electric_share"]["share"] < 1 and v["charging_home"]["full_h"]
    assert v["cost_per_100km"]["public_eur"] > v["cost_per_100km"]["home_eur"]
    assert v["range"]["real_km"] < 80 and v["range"]["real_basis"] == "ASSUMPTION"
    assert b["not_electric"][0]["cost_per_100km_eur"] > v["cost_per_100km"]["used_eur"]


def test_no_section_without_an_electric_car():
    ateca = tco.TcoCar("a", "SEAT Ateca", "ICE", "petrol", consumption=6.3, vehicle_class="compact", use=USE)
    assert electric_block.build([car()], [ateca], [tco.compute(ateca, RATES, 18000)], RATES, {}, "en") is None
