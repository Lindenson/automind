"""Meaning rules for electric values: the regression set of spec 006 SC-003."""

import pytest

from automind.domain import sense_ev as se
from automind.domain import specs
from automind.domain.units import UnitError

PHEV = [
    # (attribute, raw, unit, excerpt) -> attribute or None (rejected)
    ("consumption", "0,9", "l/100 km", "Consumo WLTP ponderado: 0,9 l/100 km", "consumption_weighted"),
    ("consumption", "0.9", "l/100 km", "Fuel consumption (WLTP combined): 0.9 l/100 km", "consumption_weighted"),
    ("consumption", "1,2", "l/100 km", "Consumo combinado 1,2 l/100 km", "consumption_weighted"),
    ("consumption", "6,1", "l/100 km", "Consumo con batería descargada 6,1 l/100 km", "consumption_cs"),
    ("consumption", "5,3", "l/100 km", "En modo híbrido gasta 5,3 l/100 km", "consumption_cs"),
    ("consumption_real", "6.4", "l/100 km", "With the battery depleted it used 6.4 l/100 km", "consumption_cs"),
    ("consumption", "5,8", "l/100 km", "Consumo 5,8 l/100 km", None),
    ("consumption_real", "5,6", "l/100 km", "En nuestra prueba gastó 5,6 l/100 km", None),
    ("consumption_weighted", "1,0", "l/100 km", "WLTP gewichtet 1,0 l/100 km", "consumption_weighted"),
    ("consumption", "18,9", "kWh/100 km", "Consumo eléctrico 18,9 kWh/100 km", "consumption_ev"),
    ("consumption_real", "21", "kWh/100 km", "21 kWh/100 km medidos en el enchufe", "consumption_ev_plug"),
    ("consumption_ev_real", "21", "kWh/100 km", "21 kWh/100 km medidos en el enchufe", "consumption_ev_plug"),
    ("consumption_ev_real", "17", "kWh/100 km", "el ordenador marcó 17 kWh/100 km", "consumption_ev_real"),
    ("consumption_cs", "5,9", "l/100 km", "Leerer Akku: 5,9 l/100 km", "consumption_cs"),
]


@pytest.mark.parametrize(("attr", "raw", "unit", "excerpt", "want"), PHEV)
def test_plug_in_consumption_by_its_words(attr, raw, unit, excerpt, want):
    r = se.plug_in_consumption(attr, raw, unit, excerpt)
    assert (r.attribute if r.ok else None) == want


CLAIMS = [
    ("charge_dc_peak_kw", "60", "kWh", "Batería de 60 kWh y carga a 135 kW", "sense.ev.energy_for_power"),
    ("charge_ac_kw", "60", "kW", "Batería de 60 kWh", "sense.ev.energy_for_power"),
    ("battery_kwh", "11", "kW", "Cargador de a bordo de 11 kW", "sense.ev.power_for_energy"),
    ("battery_kwh", "11", "kWh", "Cargador de a bordo de 11 kW", "sense.ev.power_for_energy"),
    ("charge_dc_10_80_min", "28", "min", "Del 10 al 80 % en 28 minutos", None),
    ("charge_dc_10_80_min", "26", "min", "10–80% in 26 min", None),
    ("charge_dc_10_80_min", "30", "min", "20-80 % en 30 min", None),
    ("charge_dc_10_80_min", "45", "min", "Del 0 al 100 % en 45 minutos", "sense.ev.dc_window"),
    ("charge_dc_peak_kw", "135", "kW", "Carga rápida de hasta 135 kW", None),
    ("battery_kwh", "60,5", "kWh", "Batería LFP de 60,5 kWh", None),
]


@pytest.mark.parametrize(("attr", "raw", "unit", "excerpt", "rule"), CLAIMS)
def test_single_value_rules(attr, raw, unit, excerpt, rule):
    r = se.check_claim(attr, raw, unit, excerpt)
    assert (None if r.ok else r.rule_id) == rule


@pytest.mark.parametrize(
    ("raw", "excerpt", "want"),
    [
        ("82", "Batería de 82 kWh brutos (77 kWh útiles)", "battery_kwh"),
        ("82", "Capacidad bruta 82 kWh", "battery_gross_kwh"),
        ("79", "Gross battery capacity 79 kWh", "battery_gross_kwh"),
        ("77", "Usable capacity 77 kWh", "battery_kwh"),
        ("18,3", "Batería de 18,3 kWh", "battery_kwh"),
    ],
)
def test_gross_vs_usable(raw, excerpt, want):
    assert se.battery_kind(raw, excerpt) == want


@pytest.mark.parametrize(
    ("attr", "value", "known", "rule"),
    [
        ("range_wltp", 900, {"battery_kwh": 40}, "sense.ev.range_above_battery"),
        ("range_wltp", 380, {"battery_kwh": 40}, None),
        ("range_real", 600, {"battery_kwh": 40}, "sense.ev.range_above_battery"),
        ("charge_dc_peak_kw", 400, {"battery_kwh": 50}, "sense.ev.c_rate"),
        ("charge_dc_peak_kw", 150, {"battery_kwh": 50}, None),
        ("battery_kwh", 85, {"battery_gross_kwh": 82}, "sense.ev.gross_usable_ratio"),
        ("battery_kwh", 50, {"battery_gross_kwh": 82}, "sense.ev.gross_usable_ratio"),
        ("battery_kwh", 77, {"battery_gross_kwh": 82}, None),
        ("battery_gross_kwh", 70, {"battery_kwh": 77}, "sense.ev.gross_usable_ratio"),
        ("range_wltp", 500, {}, None),
    ],
)
def test_pair_checks(attr, value, known, rule):
    r = se.pair_check(attr, value, known)
    assert (None if r.ok else r.rule_id) == rule


def test_units_convert_or_refuse():
    a = specs.ATTRS
    assert a["range_wltp"].convert(100, "miles") == pytest.approx(160.9, abs=0.1)
    assert a["consumption_ev"].convert(155, "Wh/km") == 15.5
    assert a["charge_dc_10_80_min"].convert(0.5, "h") == 30
    for key, unit in (("battery_kwh", "kW"), ("charge_ac_kw", "kWh"), ("consumption_ev", "l/100 km"),
                      ("consumption_cs", "kWh/100 km")):  # fmt: skip
        with pytest.raises(UnitError):
            a[key].convert(10, unit)


def test_range_conditions_and_warranty():
    assert se.range_conditions("Prueba en invierno a 2 °C: 310 km") == "winter"
    assert se.range_conditions("A 120 km/h por autopista recorrió 280 km") == "motorway"
    assert se.range_conditions("En verano hizo 420 km") == "summer"
    assert se.range_conditions("Autonomía real 390 km") == "mixed"
    assert se.split_warranty("8 años o 160.000 km, 70 %") == {"years": 8, "km": 160000, "soh_pct": 70}
    assert se.split_warranty("8 years / 250,000 km") == {"years": 8, "km": 250000}


@pytest.mark.parametrize(
    "excerpt",
    ["Capacité brute de la batterie 18.3 kWh", "Capacità lorda della batteria 18.3 kWh",
     "Capacitatea brută a bateriei 18.3 kWh", "Capacidad bruta de batería 18.3 kWh"],
)  # fmt: skip
def test_gross_in_the_languages_of_the_byd_pages(excerpt):
    assert se.battery_kind("18.3", excerpt) == "battery_gross_kwh"
