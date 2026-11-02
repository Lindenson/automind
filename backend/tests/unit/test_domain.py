import pytest

from automind.domain import dragrace, evidence, specs, units
from automind.domain import metrics as scoring
from automind.domain.evidence import ClaimIn


# ---- units / normalization ----
@pytest.mark.parametrize(
    "raw,unit,expected",
    [
        ("245", "PS", 180.2),
        ("180", "kW", 180.0),
        ("241 hp", "hp", 179.7),
        ("300 CV", "CV", 220.6),
    ],
)
def test_power(raw, unit, expected):
    assert specs.normalize(specs.ATTRS["max_power"], raw, unit) == pytest.approx(expected, abs=0.1)


def test_european_thousands_mass():
    assert specs.normalize(specs.ATTRS["curb_mass"], "1.430", "kg") == 1430
    assert specs.normalize(specs.ATTRS["curb_mass"], "3,153 lbs", "lb") == pytest.approx(1430.2, abs=0.1)


def test_implausible_rejected():
    with pytest.raises(units.UnitError):
        specs.normalize(specs.ATTRS["max_power"], "5", "kW")


def test_drivetrain():
    assert specs.normalize(specs.ATTRS["drivetrain"], "Dual Motor All-Wheel Drive", None) == "AWD"
    assert specs.normalize(specs.ATTRS["drivetrain"], "tracción delantera", None) == "FWD"


def test_parse_number_formats():
    assert units.parse_number("1.234,5") == 1234.5
    assert units.parse_number("1,234.5") == 1234.5
    assert units.parse_number("6,2 s") == 6.2
    assert units.parse_number("5000-6500 rpm") == 5000


# ---- evidence ----
DOC = "The Golf GTI produces 180 kW (245 PS) between 5,000 and 6,500 rpm.  Kerb weight: 1.429 kg."


def test_excerpt_validation():
    assert evidence.validate_excerpt("produces 180 kW (245 PS)", "180 kW", DOC)
    assert evidence.validate_excerpt("Kerb   weight: 1.429 kg", "1.429", DOC)
    assert not evidence.validate_excerpt("produces 190 kW", "190", DOC)  # not in doc
    assert not evidence.validate_excerpt("produces 180 kW (245 PS)", "200", DOC)  # value not in excerpt


def test_source_classification_and_provenance():
    assert evidence.classify_source("https://www.volkswagen.es/es/modelos/golf-gti.html") == "MANUFACTURER"
    assert evidence.classify_source("https://en.wikipedia.org/wiki/Golf") == "ENCYCLOPEDIA"
    assert evidence.classify_source("https://www.ultimatespecs.com/x") == "SPEC_DATABASE"
    assert evidence.classify_source("https://www.km77.com/x") == "PUBLICATION"
    assert evidence.is_denied("https://www.coches.net/x")
    assert evidence.assign_provenance("MANUFACTURER", "max_power") == "MANUFACTURER_CLAIM"
    assert evidence.assign_provenance("INSTRUMENTED_TEST", "max_power") == "SOURCED_FACT"


def _c(i, v, st, dom, scope="VARIANT", attr="max_power"):
    return ClaimIn(str(i), attr, v, st, dom, scope)


def test_select_manufacturer_wins():
    s = evidence.select_value(
        "max_power", [_c(1, 180.0, "PUBLICATION", "a.com"), _c(2, 195.0, "MANUFACTURER", "vw.es")]
    )
    assert s.value == 195.0 and s.confidence == "HIGH" and s.resolution_rule == "AUTHORITY_ORDER" and s.conflict


def test_select_two_independent_agree_high():
    s = evidence.select_value("max_power", [_c(1, 180.0, "PUBLICATION", "a.com"), _c(2, 181.0, "PUBLICATION", "b.com")])
    assert s.confidence == "HIGH" and s.confidence_rule == "HIGH:2_INDEPENDENT_AGREE"


def test_select_majority_and_unresolved():
    s = evidence.select_value(
        "max_power",
        [
            _c(1, 180.0, "PUBLICATION", "a.com"),
            _c(2, 180.0, "PUBLICATION", "b.com"),
            _c(3, 200.0, "PUBLICATION", "c.com"),
        ],
    )
    assert s.value == 180.0 and s.resolution_rule == "MAJORITY_SAME_RANK"
    u = evidence.select_value("max_power", [_c(1, 180.0, "PUBLICATION", "a.com"), _c(2, 200.0, "PUBLICATION", "b.com")])
    assert u.confidence == "LOW" and u.confidence_rule == "LOW:UNRESOLVED_CONFLICT" and u.alternatives


def test_single_source_medium_and_indirect_low():
    assert evidence.select_value("max_power", [_c(1, 180.0, "PUBLICATION", "a.com")]).confidence == "MEDIUM"
    assert evidence.select_value("max_power", [_c(1, 180.0, "PUBLICATION", "a.com", "GENERATION")]).confidence == "LOW"
    assert not evidence.select_value("max_power", []).available


# ---- drag race ----
GOLF = dragrace.CarInput("g", "Golf GTI", "ICE", 180, 1430, "FWD", "DSG", 250, "HATCHBACK", claimed_0_100=6.2)
TESLA = dragrace.CarInput("t", "Model 3 P", "BEV", 393, 1850, "AWD", None, 262, "SEDAN", claimed_0_100=3.1)


def test_race_deterministic_and_plausible():
    r1 = dragrace.simulate([GOLF, TESLA])
    r2 = dragrace.simulate([GOLF, TESLA])
    assert r1.input_hash == r2.input_hash
    assert [(x.t_0_100, x.t_400m) for x in r1.results] == [(x.t_0_100, x.t_400m) for x in r2.results]
    g = next(x for x in r1.results if x.car_id == "g")
    t = next(x for x in r1.results if x.car_id == "t")
    assert 5.0 < g.t_0_100 < 8.0 and 2.5 < t.t_0_100 < 5.0
    assert t.rank == 1 and g.t_400m > t.t_400m


def test_race_monotonic_and_wet_and_excluded():
    base = dragrace.simulate([GOLF]).results[0]
    stronger = dragrace.simulate([dragrace.CarInput(**{**GOLF.__dict__, "power_kw": 220})]).results[0]
    heavier = dragrace.simulate([GOLF], dragrace.RaceSettings(extra_load_kg=200)).results[0]
    wet = dragrace.simulate([GOLF], dragrace.RaceSettings(surface="WET")).results[0]
    assert stronger.t_400m <= base.t_400m <= heavier.t_400m
    assert wet.t_0_100 >= base.t_0_100
    r = dragrace.simulate([dragrace.CarInput("x", "X", "ICE", None, 1400)])
    assert r.excluded and not r.results


def test_hybrid_note_and_assumptions_listed():
    r = dragrace.simulate([dragrace.CarInput("h", "PHEV", "PHEV", 200, 1700)]).results[0]
    assert "combined system power simplification" in r.notes
    names = {a["name"] for a in r.assumptions}
    assert {"drag_coefficient", "frontal_area", "drivetrain", "top_speed"} <= names


# ---- metrics ----
def test_metrics():
    g = scoring.CarFacts(
        "g", "Golf", "ICE", 180, 370, 1430, 1984, "FWD", 250, 7.2, 374, 5, 48000, sim_0_100=6.5, sim_400m=14.8
    )
    t = scoring.CarFacts(
        "t", "Tesla", "BEV", 393, 660, 1850, None, "AWD", 262, 16.5, 594, 5, 55000, sim_0_100=3.6, sim_400m=11.9
    )
    assert scoring.metrics(g)["power_to_weight"] == 125.9
    assert scoring.metrics(t)["specific_output"] is None


def test_ranges_and_consumption_units_rejected():
    with pytest.raises(units.UnitError):
        specs.normalize(specs.ATTRS["curb_mass"], "1381-1502 kg", "kg")
    with pytest.raises(units.UnitError):
        specs.normalize(specs.ATTRS["consumption"], "30 mpg", "mpg")
    assert specs.normalize(specs.ATTRS["consumption"], "7,2", "l/100 km") == 7.2


def test_extended_attributes_normalize():
    A = specs.ATTRS
    assert specs.normalize(A["ground_clearance"], "21,5", "cm") == 215
    assert specs.normalize(A["bore"], "82.5", "mm") == 82.5
    assert specs.normalize(A["compression_ratio"], "9.6", None) == 9.6
    assert specs.normalize(A["euro_ncap_stars"], "5", None) == 5
    assert specs.normalize(A["low_range"], "2-speed transfer case with low range", None) == "YES"
    assert specs.normalize(A["drag_coefficient"], "0.29", None) == 0.29
    with pytest.raises(units.UnitError):
        specs.normalize(A["ground_clearance"], "1200", "mm")
    with pytest.raises(units.UnitError):
        specs.normalize(A["gear_count"], "6.5", None)
    assert A["measured_0_100"].category == "measured" and A["bore"].tier == 2


def test_variant_match_uncertain_trigger():
    u = evidence.variant_match_uncertain
    others = ["J120", "J150", "J250"]
    assert not u("The Prado J150 3.0 D-4D has 173 PS", "", "J150", others, (2009, 2023))
    assert u("Compared with the new J250, the J150 ...", "", "J150", others, (2009, 2023))
    assert not u("Land Cruiser Prado (2016) review", "", "J150", others, (2009, 2023))
    assert u("Land Cruiser Prado review", "", "J150", others, (2009, 2023))
    assert not u("j1500 truck", "J150 page", "J150", ["J15"], (None, None))


def test_variant_match_uncertain_detects_sibling_codes_without_config():
    u = evidence.variant_match_uncertain
    assert u("Racer Mk1 specs. The later Mk2 is heavier.", "", "Mk1", [], (2024, None))
    assert not u("Racer Mk1 specs.", "", "Mk1", [], (2024, None))
    assert u("Prado J150 vs J250", "", "J150", [], (2009, 2023))
