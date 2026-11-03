"""Sense checks (spec 004 FR-027, SC-010): the 2026-11-02 defect regression set."""

from __future__ import annotations

import pytest

from automind.domain import sense
from automind.domain.tco import TcoCar, TcoRates, energy_consumption
from automind.infrastructure.config import rates

# --- consumption cycles: Prado J150 7.4 l/100 km was NEDC, compared with a WLTP Tucson (user report) -----------


@pytest.mark.parametrize(
    ("excerpt", "gen_from", "source", "attr"),
    [
        ("Fuel consumption (economy) - combined (NEDC) 8.1 l/100 km", 2009, None, "consumption_nedc"),
        ("Medio 7,4 l/100 km", 2009, "SPEC_DATABASE", "consumption_nedc"),  # pre-WLTP generation, no marker
        ("Fuel Consumption - Economy - Combined WLTP: 6.8 L/100 km", 2021, None, "consumption"),
        ("Consumo combinado 7.9 l/100 km", 2024, None, "consumption"),  # current generation: WLTP
        ("Consumo real en nuestra prueba: 12,6 l/100 km", 2009, None, "consumption_real"),
        ("We averaged 34 mpg on test", 2021, "PUBLICATION", "consumption_real"),
        ("Average 11.9 l/100 km", 2021, "INSTRUMENTED_TEST", "consumption_real"),
    ],
)
def test_consumption_is_filed_under_its_cycle(excerpt: str, gen_from: int, source: str | None, attr: str) -> None:
    r = sense.classify_consumption("7.4", excerpt, gen_from, source)
    assert r.ok and r.attribute == attr


def test_epa_figures_are_not_comparable() -> None:
    r = sense.classify_consumption("29 mpg US", "EPA combined 29 mpg US", 2021)
    assert not r.ok and r.rule_id == "sense.consumption.other_cycle"


def test_manufacturer_wltp_range_gives_its_upper_bound() -> None:
    """toyota.es "10.4 - 10.8 l/100 km" was rejected as a range; it is the most reliable figure."""
    r = sense.classify_consumption("10.4 - 10.8 l/100 km", "Consumo combinado WLTP (l/100 km) : 10.4 - 10.8", 2024)
    assert r.ok and r.attribute == "consumption" and r.value == "10.8"


def test_fuel_bill_uses_real_world_consumption() -> None:
    r = TcoRates.from_config(rates())
    prado = TcoCar("p", "Prado", "MHEV", fuel="diesel", consumption=10.8)
    used, how = energy_consumption(prado, r)
    assert used is not None and 12 <= used <= 13 and "allowance" in how
    tested = TcoCar("p", "Prado", "MHEV", fuel="diesel", consumption=10.8, consumption_real=13.1)
    assert energy_consumption(tested, r)[0] == 13.1
    nedc_only = TcoCar("p", "Prado", "ICE", fuel="diesel", consumption_nedc=7.4)
    used, how = energy_consumption(nedc_only, r)
    assert used is not None and used > 10 and "NEDC" in how


# --- service intervals --------------------------------------------------------------------------------------


def test_interval_16_is_16000_km() -> None:
    assert sense.interval_km(16) == 16000
    assert sense.interval_km(15000) == 15000
    assert sense.interval_km(1) is None
    assert sense.interval_km(500_000) is None


def test_years_read_as_months() -> None:
    assert sense.interval_months(5, "every 5 years or 150,000 km") == 60
    assert sense.interval_months(12, "cada 12 meses") == 12
    assert sense.interval_months(2, "every 2 years") == 24


# --- gearbox -------------------------------------------------------------------------------------------------


def test_one_speed_ecvt_has_no_gear_count() -> None:
    r = sense.gear_count(1, "e-CVT (power-split hybrid)", "HEV")
    assert not r.ok and r.rule_id == "sense.gear_count.no_steps"
    assert not sense.gear_count(1, None, "HEV").ok
    assert not sense.gear_count(1, None, "ICE").ok
    assert sense.gear_count(6, "automatic 6-speed", "ICE").ok


def test_gearbox_of_another_variant() -> None:
    """CX-5: "manual" and "automatic 6-speed" were accepted together."""
    assert sense.gearbox_conflict("automatic", "manual 6-speed")
    assert sense.gearbox_conflict("manual", "automatic 6-speed")
    assert not sense.gearbox_conflict("e-cvt", "automatic")  # many sources call an e-CVT "automatic"
    assert sense.gearbox_conflict("e-cvt", "dual-clutch 7-speed")
    assert not sense.gearbox_conflict(None, "manual")
    assert sense.drive_conflict("FWD", "AWD") and not sense.drive_conflict(None, "AWD")


# --- computed results ---------------------------------------------------------------------------------------


def test_tco_of_513k_a_year_is_flagged() -> None:
    r = sense.tco_per_year(513_672, 0)
    assert not r.ok and r.rule_id == "sense.tco.out_of_range"
    assert sense.tco_per_year(4_200, 0).ok
    assert sense.tco_per_year(20_000, 30).ok  # very old cars are outside the rule


def test_automatic_with_manual_mode_is_automatic() -> None:
    """Prado J250: "automático con modo manual de ocho marchas" was rejected as a manual (repair 2026-11-02)."""
    assert sense.gearbox_family("automático con cambio automático con modo manual de ocho marchas") == "automatic"
    assert not sense.gearbox_conflict("automatic", "automático con modo manual de ocho marchas")
    assert not sense.gearbox_conflict("e-cvt", "1 speed CVT")  # CR-V / RAV4 hybrids
    assert sense.gearbox_conflict("automatic", "6 marchas, transmisión manual")


def test_service_interval_from_schedule_takes_the_normal_schedule() -> None:
    items = [("oil and filter", 5000, None), ("engine oil & filter change", 10000, 12), ("air filter", 40000, None)]
    assert sense.service_interval_from_items(items) == (10000, 12)
    assert sense.service_interval_from_items([("air filter", 40000, None)]) == (None, None)


@pytest.mark.parametrize(
    ("url", "ok"),
    [
        ("https://www.hyundai.com/content/dam/hyundai/my/en/data/marketing/maintenance/tucson/x.pdf", False),
        ("https://www.hyundai.com/es/es/modelos/tucson.html", True),
        ("https://www.carsguide.com.au/x", False),
        ("https://www.edmunds.com/toyota/rav4/", False),
        ("https://www.parkers.co.uk/x", True),
        ("https://www.km77.com/coches/hyundai", True),
    ],
)
def test_maintenance_schedule_must_be_european(url: str, ok: bool) -> None:
    assert sense.market_fits(url, "maintenance").ok is ok


def test_price_needs_its_currency_spec_005() -> None:
    """Live chat 2026-11-03: "150 159 4,75%" (150 CV, 159 g/km CO2, 4.75 % tax) was read as €150,159."""
    from automind.domain.sense import money_marked, price_outliers

    assert not money_marked("150 159", "1.5 EcoTSI 110kW (150CV) DSG-7 St&Sp FR SPECIAL EDITION 150 159 4,75%").ok
    assert money_marked("39.302", "1.5 TSI 110kW (150CV) DSG-7 St&Sp FR2026\n\n39.302 €").ok
    assert money_marked("28.810,00", "1.5 EcoTSI 150 CV DSG-7 S&S Style | 28.810,00 €").ok
    assert money_marked("37.540", "**28.465 €** P.V.P. 37.540 €").ok
    assert money_marked("41635", "1.5 TSI 150 CV DSG 7v | 41.635 euros").ok
    assert price_outliers([29190, 30706, 39302, 150159, 31092]) == {3}
    assert price_outliers([29190, 30706]) == set()
