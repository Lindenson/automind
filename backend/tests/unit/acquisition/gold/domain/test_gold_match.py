"""Gold matching: dataset rows -> gold values of one variant (spec 011 T013, research R3)."""

from automind.acquisition.gold.domain.choice import flag
from automind.acquisition.gold.domain.config import MatchCfg
from automind.acquisition.gold.domain.match import match
from automind.acquisition.gold.domain.records import DatasetRow, VariantKey
from automind.acquisition.gold.domain.text import weighted_median

CFG = MatchCfg(
    aliases={"BMW": ["bmw", "bayerische motoren werke"], "Toyota": ["toyota"], "Kia": ["kia"]},
    strip_words=("series", "serie", "xdrive", "hybrid", "phev"),
    tolerances={
        "max_power": ("rel", 0.02),
        "curb_mass": ("rel", 0.03),
        "displacement": ("abs", 10.0),
        "co2_wltp": ("rel", 0.03),
    },  # fmt: skip
    conversions={"eu_running_order_minus_driver": -75.0},
)
UNITS = {"max_power": "kW", "curb_mass": "kg", "displacement": "cm3", "co2_wltp": "g/km"}
V520D = VariantKey(variant_id="v-520d", make="BMW", model="5 Series", model_tokens=("5",), fuel="diesel",
                   power_kw=140, years=(2017, 2023))  # fmt: skip


def row(**kw) -> DatasetRow:
    values = kw.pop("values", {"max_power": 140.0, "co2_wltp": 130.0, "displacement": 1995.0, "curb_mass": 1540.0})
    base = {"dataset": "eea_co2", "make": "BAYERISCHE MOTOREN WERKE", "model": "520D XDRIVE 5 SERIES",
            "fuel": "diesel", "power_kw": 140.0, "displacement_cc": 1995, "mass_running_order_kg": 1540.0,
            "year_from": 2021, "year_to": 2021, "registrations": 100, "values": values,
            "units": {k: UNITS.get(k, "") for k in values}, "record_key": "k1",
            "conversions": {"curb_mass": "eu_running_order_minus_driver"} if "curb_mass" in values else {}}  # fmt: skip
    return DatasetRow(**{**base, **kw})


def by_attr(gold):
    return {g.attribute: g for g in gold}


def test_exact_match_is_high_and_converts_running_order_mass():
    gold = by_attr(match([row()], V520D, CFG, dataset_id="eea_co2_2024"))
    assert gold["co2_wltp"].value_num == 130.0 and gold["co2_wltp"].match_rule == "exact"
    assert gold["co2_wltp"].confidence == "HIGH" and gold["co2_wltp"].unit == "g/km"
    assert gold["max_power"].value_num == 140.0
    assert gold["curb_mass"].value_num == 1465.0
    assert gold["curb_mass"].match_rule == "exact+eu_running_order_minus_driver"
    assert gold["curb_mass"].tolerance == 0.03 and gold["curb_mass"].tolerance_kind == "rel"
    assert all(g.origin == "dataset" and g.dataset_id == "eea_co2_2024" for g in gold.values())


def test_power_within_one_kw_and_other_keys_must_match():
    assert match([row(power_kw=141.0)], V520D, CFG)
    assert not match([row(power_kw=143.0)], V520D, CFG)  # another engine
    assert not match([row(fuel="petrol")], V520D, CFG)
    assert not match([row(make="AUDI")], V520D, CFG)
    assert not match([row(model="X5 XDRIVE30D")], V520D, CFG)  # the model tokens are not there
    assert not match([row(year_from=2012, year_to=2013)], V520D, CFG)  # registered outside the generation's years
    assert not match([row(registrations=1)], V520D, CFG)  # a single vehicle is noise


def test_no_power_on_the_variant_and_a_unique_group_matches_by_power():
    v = VariantKey(variant_id="v", make="BMW", model="5 Series", model_tokens=("5",), fuel="diesel", power_kw=None,
                   years=(2017, 2023))  # fmt: skip
    gold = by_attr(match([row(), row(record_key="k2", year_from=2022, year_to=2022, registrations=50)], v, CFG))
    assert gold["max_power"].match_rule == "by_power" and gold["max_power"].confidence == "MEDIUM"
    assert gold["max_power"].value_num == 140.0


def test_two_groups_beyond_tolerance_give_no_gold():
    v = VariantKey(variant_id="v", make="BMW", model="5 Series", model_tokens=("5",), fuel="diesel", power_kw=None,
                   years=(2017, 2023))  # fmt: skip
    other = {"max_power": 210.0, "co2_wltp": 160.0, "displacement": 2993.0, "curb_mass": 1720.0}
    rows = [
        row(),
        row(record_key="k2", power_kw=210.0, displacement_cc=2993, values=other, mass_running_order_kg=1720.0),
    ]
    assert match(rows, v, CFG) == []


def test_mass_breaks_a_tie_between_groups():
    v = VariantKey(variant_id="v", make="BMW", model="5 Series", model_tokens=("5",), fuel="diesel", power_kw=140,
                   years=(2017, 2023), mass=1470.0)  # fmt: skip
    heavy = {"max_power": 140.0, "co2_wltp": 150.0, "displacement": 2500.0, "curb_mass": 1800.0}
    rows = [row(), row(record_key="k2", displacement_cc=2500, values=heavy, mass_running_order_kg=1800.0)]
    gold = by_attr(match(rows, v, CFG))
    assert gold["co2_wltp"].value_num == 130.0


def test_registration_weighted_median():
    assert weighted_median([(130.0, 10), (132.0, 100), (140.0, 5)]) == 132.0
    assert weighted_median([(1.0, 1)]) == 1.0
    rows = [row(values={"co2_wltp": 128.0}, registrations=10),
            row(record_key="k2", values={"co2_wltp": 130.0}, registrations=300, year_from=2022, year_to=2022),
            row(record_key="k3", values={"co2_wltp": 131.0}, registrations=20, year_from=2023,
                year_to=2023)]  # fmt: skip
    gold = by_attr(match(rows, V520D, CFG))
    assert gold["co2_wltp"].value_num == 130.0 and gold["co2_wltp"].registrations == 330


def test_hybrid_engine_power_is_not_compared_with_the_system_power():
    """EEA/RDW give the combustion engine's kW for HEV/PHEV (Sorento PHEV: 132 kW engine, 195 kW system)."""
    v = VariantKey(variant_id="v", make="Kia", model="Sorento", model_tokens=("sorento",), fuel="phev", power_kw=195,
                   years=(2020, 2024), displacement_cc=1598)  # fmt: skip
    phev = row(make="KIA", model="SORENTO", fuel="phev", power_kw=132.0, displacement_cc=1598,
               values={"co2_wltp": 38.0, "curb_mass": 2025.0})  # fmt: skip
    gold = by_attr(match([phev], v, CFG))
    assert "max_power" not in gold and gold["co2_wltp"].value_num == 38.0
    assert gold["co2_wltp"].match_rule == "by_power" and gold["co2_wltp"].confidence == "MEDIUM"
    assert not match([row(make="KIA", model="SORENTO", fuel="phev", power_kw=132.0, displacement_cc=2151)], v, CFG)


def test_free_text_commercial_names():
    v = VariantKey(variant_id="v", make="Toyota", model="Land Cruiser", model_tokens=("land", "cruiser"),
                   fuel="diesel", power_kw=150, years=(2010, 2023))  # fmt: skip
    for name in ("TOYOTA LAND CRUISER (150 SERIES)", "LANDCRUISER", "LAND CRUISER (150 SERIE"):
        assert match([row(make="TOYOTA", model=name, power_kw=150.0)], v, CFG), name
    assert not match([row(make="TOYOTA", model="RAV4", power_kw=150.0)], v, CFG)


def test_flag_when_two_independent_families_agree_against_gold():
    g = by_attr(match([row()], V520D, CFG))["curb_mass"]  # 1465 kg
    flagged, reason = flag(g, {"km77": 1540.0, "ultimatespecs": 1545.0}, ("rel", 0.03))
    assert flagged and "1465" in reason
    assert flag(g, {"km77": 1540.0}, ("rel", 0.03)) == (False, None)  # one family is not enough
    assert flag(g, {"km77": 1540.0, "ultimatespecs": 1700.0}, ("rel", 0.03)) == (False, None)  # they disagree
    assert flag(g, {"km77": 1470.0, "ultimatespecs": 1468.0}, ("rel", 0.03)) == (False, None)  # they agree with gold
