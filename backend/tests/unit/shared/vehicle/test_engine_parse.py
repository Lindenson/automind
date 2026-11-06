"""Engine as part of the identity (spec 005 R4, FR-012): deterministic parsing of the user's words."""

from automind.shared.vehicle.identity import engine_fits, parse_engine


def test_displacement_forms() -> None:
    for text in ("1.5", "1,5", "Ateca 1.5 двигатель", "Seat 1.5 двигатель", "мотор 1.5 литра", "1.5L"):
        e = parse_engine(text)
        assert e is not None and e.displacement_l == 1.5, text
    e = parse_engine("1500 cc")
    assert e is not None and e.displacement_l == 1.5


def test_full_engine_name() -> None:
    e = parse_engine("1.5 TSI 150 CV")
    assert e is not None
    assert (e.displacement_l, e.power_hp, e.power_kw, e.family, e.fuel) == (1.5, 150, 110, "TSI", "petrol")
    e = parse_engine("2.0 TDI 110 kW")
    assert e is not None and (e.displacement_l, e.power_kw, e.fuel) == (2.0, 110, "diesel")
    e = parse_engine("150 л.с.")
    assert e is not None and e.power_hp == 150 and e.power_kw == 110


def test_fuel_words() -> None:
    assert (parse_engine("BYD Seal U DM-i") or _none()).fuel == "phev"
    assert (parse_engine("версия eléctrico") or _none()).fuel == "bev"
    assert (parse_engine("электро") or _none()).fuel == "bev"
    assert (parse_engine("хочу дизель") or _none()).fuel == "diesel"
    assert (parse_engine("plug-in hybrid") or _none()).fuel == "phev"
    assert (parse_engine("гибрид") or _none()).fuel == "hybrid"


def test_negation_keeps_the_other_value() -> None:
    for text in ("not 1.0 but 1.5", "1.5, а не 1.0", "не 1.0, а 1.5", "ты написал 1.0, но это не то, 1.5"):
        e = parse_engine(text)
        assert e is not None and e.displacement_l == 1.5, text


def test_years_and_km_are_not_engines() -> None:
    assert parse_engine("2025 года") is None
    assert parse_engine("60 000 km") is None
    assert parse_engine("80 тыс км, 2019") is None
    assert parse_engine("1-2 тыс км в месяц") is None
    assert parse_engine("для семьи") is None


def test_engine_fits() -> None:
    e = parse_engine("1.5 TSI 150 CV")
    assert e is not None
    assert engine_fits(e, 1498, 110, "petrol")
    assert not engine_fits(e, 999, 81, "petrol")
    assert engine_fits(e, None, None, None)  # unknown engine of the variant: not excluded
    d = parse_engine("дизель")
    assert d is not None and not engine_fits(d, 1968, 110, "petrol")


def _none():  # noqa: ANN202 - helper to fail loudly with an attribute error
    raise AssertionError("parse_engine returned None")
