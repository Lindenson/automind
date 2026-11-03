"""Parser defects from the critic review (hardening): units in the raw text, seats, decimal commas, mpg, engine fuel."""

import pytest

from automind.domain import specs, units
from automind.domain.identity import parse_engine

A = specs.ATTRS


# 3.1 a unit written in the raw string is detected: miles never pass as km
def test_service_interval_miles_converted() -> None:
    assert specs.normalize(A["service_interval_km"], "20 000 miles", None) == pytest.approx(32186.88)
    assert specs.normalize(A["service_interval_km"], "12,500 mi", "km") == pytest.approx(20116.8)
    assert specs.normalize(A["service_interval_km"], "30.000 km", None) == 30000
    assert specs.normalize(A["service_interval_km"], "15000", None) == 15000
    with pytest.raises(units.UnitError):
        specs.normalize(A["service_interval_km"], "15000", "hours")


# 3.2 seats "5+2" is seven seats
@pytest.mark.parametrize("raw,expected", [("5+2", 7), ("5 + 2", 7), ("5/7", 7), ("2+2", 4), ("7", 7), ("5 plazas", 5)])
def test_seats_forms(raw: str, expected: int) -> None:
    assert specs.normalize(A["seats"], raw, None) == expected


# 3.3 the unit field may be empty: the unit is found in the raw value, then in the excerpt
def test_unit_from_raw_value_and_excerpt() -> None:
    assert specs.normalize(A["max_power"], "150 hp", None) == pytest.approx(111.9, abs=0.1)
    assert specs.normalize(A["max_power"], "150 CV", None) == pytest.approx(110.3, abs=0.1)
    assert specs.normalize(A["max_power"], "110 kW (150 CV)", None) == 110
    assert specs.normalize(A["max_power"], "150", None, excerpt="Potencia máxima: 150 CV a 6.000 rpm") == (
        pytest.approx(110.3, abs=0.1)
    )
    assert specs.normalize(A["max_torque"], "250", None, excerpt="max torque 250 Nm from 1500 rpm") == 250
    with pytest.raises(units.UnitError):
        specs.normalize(A["max_power"], "150", None)
    # the raw text is the page, the unit field is the model's reading of it
    assert specs.normalize(A["max_power"], "150 hp", "kW") == pytest.approx(111.9, abs=0.1)


# 3.4 a comma is decimal when that is the reading that fits the attribute
def test_decimal_comma_displacement() -> None:
    assert specs.normalize(A["displacement"], "1,598", "l") == 1598
    assert specs.normalize(A["displacement"], "1,598", "litros") == 1598
    assert specs.normalize(A["displacement"], "1.598", "l") == 1598
    assert specs.normalize(A["displacement"], "1,598 cc", None) == 1598
    assert specs.normalize(A["displacement"], "1,6 l", None) == 1600
    assert specs.normalize(A["boot_volume"], "1,234", "l") == 1234  # thousands where that fits


# 3.5 mpg is converted (UK by default, US by unit text or US source)
def test_mpg_converted() -> None:
    c = A["consumption"]
    assert specs.normalize(c, "45 mpg", None) == pytest.approx(282.481 / 45, abs=0.001)
    assert specs.normalize(c, "45", "mpg") == pytest.approx(6.277, abs=0.001)
    assert specs.normalize(c, "45 mpg", None, domain="www.autoexpress.co.uk") == pytest.approx(6.277, abs=0.001)
    assert specs.normalize(c, "45 mpg", None, domain="https://caranddriver.com/x") == pytest.approx(5.227, abs=0.001)
    assert specs.normalize(c, "45", "mpg (US)") == pytest.approx(235.215 / 45, abs=0.001)
    assert specs.normalize(c, "45 US mpg", None) == pytest.approx(5.227, abs=0.001)
    assert specs.normalize(c, "45 mpg", None, excerpt="EPA combined 45 mpg") == pytest.approx(5.227, abs=0.001)
    assert specs.normalize(c, "45", "mpg (imp)", domain="caranddriver.com") == pytest.approx(6.277, abs=0.001)
    assert specs.normalize(c, "7,2", "l/100 km") == 7.2
    assert specs.normalize(c, "16,1 kWh/100 km", None) == 16.1


# reviewer-confirmed behaviour kept
def test_number_format_regressions() -> None:
    assert units.parse_number("1.234,5") == 1234.5
    assert units.parse_number("1,234.5") == 1234.5
    assert units.parse_number("29 990") == 29990
    assert units.parse_number("12.345,67") == 12345.67
    assert specs.normalize(A["official_price_es"], "36.075 euros", None) == 36075
    assert specs.normalize(A["official_price_es"], "29 990 €", None) == 29990
    assert specs.normalize(A["curb_mass"], "1.430 kg", None) == 1430
    assert specs.normalize(A["curb_mass"], "1.430", "kg") == 1430
    assert specs.normalize(A["claimed_0_100"], "8,9 s", None) == 8.9


# 3.6 engine fuel words
@pytest.mark.parametrize(
    "text,fuel",
    [
        ("C-HR 2.0 hybrid 197 CV", "hybrid"),
        ("Tucson 1.6 T-GDI 48V", "mhev"),
        ("Tucson 1.6 T-GDi HEV", "hybrid"),
        ("Tucson 1.6 T-GDi PHEV", "phev"),
        ("Corolla hybrid 140", "hybrid"),
        ("Golf e-Hybrid", "phev"),
        ("Golf GTE plug-in", "phev"),
        ("Kuga enchufable", "phev"),
        ("PHEV", "phev"),
        ("mild hybrid", "mhev"),
        ("MHEV", "mhev"),
        ("microhíbrido", "mhev"),
        ("Sportage 1.6 T-GDi 48 V", "mhev"),
        ("eléctrico", "bev"),
        ("Kona EV", "bev"),
        ("BEV", "bev"),
        ("híbrido", "hybrid"),
        ("híbrido eléctrico", "hybrid"),
        ("full hybrid electric", "hybrid"),
        ("2.0 TDI", "diesel"),
        ("1.5 TSI", "petrol"),
    ],
)
def test_engine_fuel_words(text: str, fuel: str) -> None:
    e = parse_engine(text)
    assert e is not None and e.fuel == fuel, (text, e)


def test_engine_fuel_word_boundaries() -> None:
    for text in ("Chevrolet", "every day", "Leverkusen", "hybridisation"):
        e = parse_engine(text)
        assert e is None or e.fuel != "bev", text


def test_engine_bare_power_after_fuel_word() -> None:
    e = parse_engine("Corolla hybrid 140")
    assert e is not None and e.power_hp == 140 and e.fuel == "hybrid"
    e = parse_engine("C-HR 2.0 hybrid 197 CV")
    assert e is not None and (e.displacement_l, e.power_hp, e.fuel) == (2.0, 197, "hybrid")
    e = parse_engine("Corolla hybrid 2021")
    assert e is not None and e.power_hp is None
    e = parse_engine("Corolla hybrid 140 000 km")
    assert e is not None and e.power_hp is None
