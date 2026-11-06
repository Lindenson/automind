"""Brands new in Spain: network counts, warranty, resale value (spec 006 US6, quickstart E)."""

from pathlib import Path

import pytest
import yaml

from automind.acquisition.domain import sense_ev
from automind.chat.domain.cost import tco
from automind.shared.vehicle.makes import MakeRegistry

CONFIG = Path(__file__).parents[4] / "config"


@pytest.mark.parametrize(
    ("number", "excerpt", "ok"),
    [
        (120, "BYD cuenta con 120 concesionarios en España", True),
        (120, "La red de MG suma ya 120 puntos de venta y servicio", True),
        (85, "85 talleres oficiales repartidos por toda España", True),
        (1200, "una red de 1.200 talleres", True),
        (120, "120 km de autonomía eléctrica y concesionarios en toda España", False),
        (120, "el motor de 120 kW", False),
        (150, "BYD vendió 150 unidades en octubre", False),
        (0.5, "0,5 concesionarios por provincia", False),
        (5000, "5000 concesionarios", False),
        (None, "una red amplia de concesionarios", True),
    ],
)
def test_count_only_next_to_a_network_word(number, excerpt, ok):
    r = sense_ev.count_context(number, excerpt)
    assert r.ok is ok
    assert r.rule_id == "sense.brand.count_context"
    if ok and number is not None:
        assert r.value == number


def test_warranty_is_split_and_checked():
    r = sense_ev.warranty_check("BATTERY_WARRANTY", "Batería: 8 años o 160.000 km, con un 70 % de capacidad")
    assert r.ok and r.value == {"years": 8.0, "km": 160000.0, "soh_pct": 70.0}
    car = sense_ev.warranty_check("WARRANTY", "Garantía de 7 años o 150.000 km")
    assert car.ok and car.value == {"years": 7.0, "km": 150000.0}
    assert not sense_ev.warranty_check("WARRANTY", "garantía de 25 años contra la corrosión").ok
    assert not sense_ev.warranty_check("BATTERY_WARRANTY", "garantía total").ok
    # a percentage on the car warranty is not a battery capacity
    assert "soh_pct" not in sense_ev.warranty_check("WARRANTY", "7 años de garantía, 100 % cubierto").value


def test_recent_makes_are_marked():
    reg = MakeRegistry.from_config(yaml.safe_load((CONFIG / "makes.yaml").read_text()))
    for make in ("BYD", "MG", "Omoda", "Jaecoo", "Leapmotor", "Xpeng", "Zeekr", "Lynk & Co", "EBRO", "DFSK"):
        assert reg.new_in_market(make), make
    assert reg.new_in_market("byd")
    assert not reg.new_in_market("SEAT") and not reg.new_in_market("Toyota") and not reg.new_in_market(None)


RATES = {
    **yaml.safe_load((CONFIG / "rates.yaml").read_text()),
    "energy": yaml.safe_load((CONFIG / "energy.yaml").read_text()),
}
CURVE = {0: 1.0, 3: 0.6, 5: 0.45}


def _car(cid: str, **kw) -> tco.TcoCar:
    return tco.TcoCar(cid, cid, "ICE", "petrol", consumption=6.0, price_eur=30000, retention_curve=CURVE, **kw)


def _dep(e: tco.TcoEstimate) -> tco.TcoItem:
    return next(i for i in e.items if i.kind == "DEPRECIATION")


def test_recent_make_has_no_class_curve():
    r = tco.TcoRates.from_config(RATES)
    mg = tco.compute(_car("mg", new_in_market=True), r, 15000)
    assert _dep(mg).annual_eur is None and "insufficient data for this brand" in _dep(mg).label
    sourced = tco.compute(_car("mg", new_in_market=True, retention={3: 0.55, 5: 0.4}), r, 15000)
    assert _dep(sourced).annual_eur is not None and _dep(sourced).basis == "SOURCED"


def test_period_totals_leave_depreciation_out_for_all_when_one_is_unknown():
    r = tco.TcoRates.from_config(RATES)
    both = [tco.compute(_car("seat"), r, 15000), tco.compute(_car("mg", new_in_market=True), r, 15000)]
    fair = tco.like_for_like(both)
    assert all(e.depreciation_left_out for e in fair)
    seat = fair[0]
    running = sum(i.five_year_eur for i in seat.items if i.kind != "DEPRECIATION" and i.five_year_eur is not None)
    assert seat.five_year_total == pytest.approx(running)
    assert seat.five_year_total < both[0].five_year_total
    known = [tco.compute(_car("seat"), r, 15000), tco.compute(_car("kia"), r, 15000)]
    assert tco.like_for_like(known) == known
