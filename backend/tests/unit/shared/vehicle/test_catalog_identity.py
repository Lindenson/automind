"""One row per car: names differ, the engine and the fields that tell versions apart do not (catalog clean-up);
an estate's boot is not the hatchback's."""

import pytest

from automind.acquisition.parsing.normalise.numbers import litres
from automind.shared.evidence import sense
from automind.shared.vehicle import identity

G20 = {"make": "BMW", "model": "3 Series", "generation": "G20", "powertrain": "MHEV", "engine_cc": 1995,
       "power_kw": 140, "transmission": "automatic", "drive": "RWD", "body_class": "SEDAN",
       "trim": "M Sport"}  # fmt: skip


def _v(i: str, **kw):
    return {**G20, "id": i, **kw}


def test_same_car_under_three_names_is_one_group():
    rows = [_v("a", variant_name="320d M Sport"), _v("b", variant_name="320d M Sport 2.0 Mild-Hybrid 190 CV"),
            _v("c", variant_name="320d M Sport 8-speed automatic"),
            _v("d", variant_name="330e", power_kw=215)]  # fmt: skip
    assert identity.duplicate_groups(rows) == [["a", "b", "c"]]


@pytest.mark.parametrize(
    "change",
    [
        {"transmission": "manual"},
        {"drive": "AWD"},
        {"power_kw": 135},
        {"generation": "F30"},
        {"trim": "Sport Line"},
        {"powertrain": "ICE"},
        {"power_kw": None},  # unknown power: not enough to call it the same car
        {"engine_cc": None},
    ],
)
def test_a_field_that_tells_versions_apart_keeps_them_apart(change):
    assert not identity.same_version(_v("a"), _v("b", **change))


def test_unknown_on_one_side_is_not_a_difference():
    assert identity.same_version(_v("a"), _v("b", generation=None, transmission=None, trim=None))
    assert identity.same_version(_v("a", engine_cc=1984), _v("b", engine_cc=1995))  # rounding of cm³


def test_a_new_car_with_a_version_name_is_not_folded_into_a_row_without_one():
    assert not identity.same_version(_v("a", trim=None), _v("b", trim="Style"), trim_unknown_ok=False)
    assert identity.same_version(_v("a"), _v("b"), trim_unknown_ok=False)


def test_rows_that_conflict_with_each_other_never_share_a_group():
    rows = [_v("x", drive=None), _v("r", drive="RWD"), _v("w", drive="AWD")]
    assert identity.duplicate_groups(rows) == [["x", "r"]]


@pytest.mark.parametrize(
    ("value", "body", "url", "ok"),
    [
        (341, "WAGON", "https://www.km77.com/coches/volkswagen/golf/2024/5-puertas/r/golf-r/datos", False),
        (611, "WAGON", "https://www.km77.com/coches/volkswagen/golf/2024/5-puertas/r/golf-r/datos", False),
        (611, "WAGON", "https://www.km77.com/coches/volkswagen/golf/2024/variant/r/golf-r-variant/datos", True),
        (341, "WAGON", "https://www.km77.com/coches/volkswagen/golf/2024/variant/r/golf-r-variant/datos", False),
        (341, "HATCHBACK", "https://www.km77.com/coches/volkswagen/golf/2024/5-puertas/r/golf-r/datos", True),
        (480, "WAGON", "", True),
        (640, "WAGON", "https://example.com/skoda-octavia-combi-5-puertas", True),
    ],
)
def test_estate_boot(value, body, url, ok):
    assert sense.boot_fits_body(value, body, url).ok is ok


@pytest.mark.parametrize(
    ("raw", "expected"), [("611", 611), ("611 l", 611), ("1.642", 1642), ("380,5", 380.5), ("", None)]
)
def test_litres(raw, expected):
    assert litres(raw) == expected
