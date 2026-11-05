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


@pytest.mark.parametrize(
    "url",
    ["https://toyota-club.net/f", "https://clubseat.es/a", "https://bmwfans.info/", "https://kiaclub.ru/",
     "https://audiworld.com/", "https://hondapartsnow.com/p", "https://img.cdn.com/mg.png", "https://marinmazda.net/",
     "https://toyota.es.example.com/", "https://nicebyd.com/"],
)  # fmt: skip
def test_brand_inside_a_name_is_not_the_manufacturer(url):
    """Reviewer 2026-11-03: a fan club, a dealer, a parts shop or a CDN got the highest authority."""
    assert evidence.classify_source(url) == "PUBLICATION"


@pytest.mark.parametrize(
    "url",
    ["https://www.toyota.es/x", "https://bmw.com.sg/", "https://owners-manual.mazda.com/", "https://byd.com/es",
     "https://seat-cupra-mediacenter.es/x", "https://press.bmwgroup.com/x", "https://www.mercedes-benz.es/",
     "https://concesionarios.seat/"],
)  # fmt: skip
def test_official_maker_sites(url):
    assert evidence.classify_source(url) == "MANUFACTURER"


def test_favourite_type_and_domain_boundary():
    assert evidence.classify_source("https://www.autopista.es/x") == "INSTRUMENTED_TEST"
    assert evidence.classify_source("https://autobild.de/x") == "INSTRUMENTED_TEST"
    assert evidence.classify_source("https://fooautobild.de/x") == "PUBLICATION"


def test_source_classification_and_provenance():
    assert evidence.classify_source("https://www.volkswagen.es/es/modelos/golf-gti.html") == "MANUFACTURER"
    assert evidence.classify_source("https://en.wikipedia.org/wiki/Golf") == "ENCYCLOPEDIA"
    assert evidence.classify_source("https://www.ultimatespecs.com/x") == "SPEC_DATABASE"
    assert evidence.classify_source("https://www.km77.com/x") == "SPEC_DATABASE"  # the favourite's own type
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
        specs.normalize(specs.ATTRS["consumption"], "18 km/l", "km/l")  # mpg is converted now (review 3.5)
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


def test_transmission_is_normalised_and_cvt_is_not_one_speed():
    from automind.domain.specs import normalize_transmission as n

    assert n("1 speed CVT") == "CVT"
    assert n("1 velocidades CVT") == "CVT"
    assert n("e-CVT") == "e-CVT (power-split hybrid)"
    assert n("6 speed Automatic") == "automatic 6-speed"
    assert n("six-speed automatic") == "automatic 6-speed"
    assert n("caja de cambios manual de seis velocidades") == "manual 6-speed"
    assert n("Manual") == "manual"
    assert n("7-speed DSG") == "dual-clutch 7-speed"
    assert n("blue") is None


def test_euro_ncap_year_and_protocol_periods():
    from automind.domain.criteria import ncap_comparable
    from automind.domain.metrics import CarFacts

    assert specs.normalize(specs.ATTRS["euro_ncap_year"], "2024", None) == 2024
    a = CarFacts(car_id="A", label="A", powertrain="ICE", euro_ncap=5, euro_ncap_year=2015)
    b = CarFacts(car_id="B", label="B", powertrain="ICE", euro_ncap=5, euro_ncap_year=2024)
    c = CarFacts(car_id="C", label="C", powertrain="ICE", euro_ncap=4, euro_ncap_year=2023)
    d = CarFacts(car_id="D", label="D", powertrain="ICE", euro_ncap=4)
    assert not ncap_comparable([a, b]) and ncap_comparable([b, c]) and ncap_comparable([a, d])


def test_favourite_query_in_the_market_language():
    from automind.domain import search_plan

    car = search_plan.Identity(make="Toyota", model="RAV4", generation="XA50", variant="2.5 Hybrid")
    favs = [
        {"domain": "adac.de", "areas": ["reliability"], "markets": ["DE"], "priority": 1},
        {"domain": "autoexpress.co.uk", "areas": ["reliability"], "markets": ["EN"], "priority": 1},
    ]
    tpl = {
        "reliability": "{make} {model} reliability {sites}",
        "reliability@DE": "{make} {model} Pannenstatistik {sites}",
    }
    qs = search_plan.queries("reliability", car, ["EN", "DE"], favs, tpl, {}, 0)
    by = {q.market: q.text for q in qs}
    assert "Pannenstatistik" in by["DE"] and "reliability" in by["EN"]
