"""Search plan (spec 003 FR-002, FR-003; research R2): favourites first, grouped, by market; open web later."""

from automind.domain import evidence
from automind.domain.search_plan import Identity, PlannedQuery, queries

FAV = [
    {
        "domain": "km77.com",
        "source_type": "SPEC_DATABASE",
        "areas": ["specs", "price"],
        "markets": ["ES"],
        "priority": 1,
    },
    {
        "domain": "ultimatespecs.com",
        "source_type": "SPEC_DATABASE",
        "areas": ["specs"],
        "markets": ["ANY"],
        "priority": 1,
    },
    {"domain": "cars-data.com", "source_type": "SPEC_DATABASE", "areas": ["specs"], "markets": ["ANY"], "priority": 1},
    {"domain": "fichasmotor.com", "source_type": "SPEC_DATABASE", "areas": ["specs"], "markets": ["ES"], "priority": 3},
    {"domain": "motor.es", "source_type": "PUBLICATION", "areas": ["specs"], "markets": ["ES"], "priority": 2},
    {"domain": "autoexpress.co.uk", "source_type": "PUBLICATION", "areas": ["specs"], "markets": ["EN"], "priority": 2},
    {
        "domain": "caranddriver.com",
        "source_type": "INSTRUMENTED_TEST",
        "areas": ["measured"],
        "markets": ["EN"],
        "priority": 1,
    },
]
TEMPLATES = {
    "specs": "{make} {model} {generation} {variant} {sites}",
    "price": "{make} {model} {variant} precio {sites}",
}
OPEN = {"specs": ["{make} {model} {generation} {variant} specifications", "{make} {model} {generation} ficha técnica"]}
CAR = Identity(make="BMW", model="5 Series", generation="G30", variant="520d", years="2017–2023")


def _plan(area, markets=("ES",), round_=0, manufacturer=None, sites_per_query=4):
    return queries(area, CAR, list(markets), FAV, TEMPLATES, OPEN, round_, manufacturer_site=manufacturer,
                   sites_per_query=sites_per_query)  # fmt: skip


def test_round0_groups_favourites_by_priority_and_market():
    qs = _plan("specs", markets=("ES",))
    assert all(isinstance(q, PlannedQuery) and q.kind == "FAVOURITE" for q in qs)
    # ES + ANY sites for specs, priority order, ≤ 4 per query
    first = qs[0]
    assert first.sites == ("km77.com", "ultimatespecs.com", "cars-data.com", "motor.es")
    assert (
        first.text
        == "BMW 5 Series G30 520d site:km77.com OR site:ultimatespecs.com OR site:cars-data.com OR site:motor.es"
    )
    assert qs[1].sites == ("fichasmotor.com",)
    assert {q.market for q in qs} == {"ES"}
    assert "autoexpress.co.uk" not in {s for q in qs for s in q.sites}


def test_market_any_matches_every_market_and_each_market_gets_its_queries():
    qs = _plan("specs", markets=("ES", "EN"))
    en = [q for q in qs if q.market == "EN"]
    assert en and en[0].sites == ("autoexpress.co.uk",)  # ANY sites were already queried for ES
    # a site already queried for another market is not queried twice
    sites = [s for q in qs for s in q.sites]
    assert len(sites) == len(set(sites))


def test_manufacturer_site_is_added_first_for_price():
    qs = _plan("price", manufacturer="bmw.es")
    assert qs[0].sites[0] == "bmw.es"
    assert "site:bmw.es" in qs[0].text


def test_open_round_uses_open_templates_without_sites():
    qs = _plan("specs", round_=1)
    assert [q.kind for q in qs] == ["OPEN", "OPEN"]
    assert qs[0].text == "BMW 5 Series G30 520d specifications"
    assert qs[0].sites == ()


def test_deny_listed_favourite_never_appears():
    evidence.configure(evidence.policy().__class__(**{**evidence.policy().__dict__, "denylist": ("motor.es",)}))
    try:
        qs = _plan("specs")
        assert "motor.es" not in {s for q in qs for s in q.sites}
    finally:
        from automind.infrastructure.config import configure_domain

        configure_domain()


def test_area_without_favourites_falls_back_to_open_templates_in_round0():
    qs = _plan("reviews")
    assert qs == []  # no favourite and no open template for reviews in this test config


def test_no_duplicate_queries():
    qs = _plan("specs", markets=("ES", "ES"))
    assert len({q.text for q in qs}) == len(qs)


def test_ai_query_checks():
    from automind.domain.search_plan import accept_ai_query

    tried = ["BMW 5 Series G30 520d specifications"]
    assert accept_ai_query("BMW G30 520d Messwerte 0-100 auto motor und sport", tried)
    assert not accept_ai_query("bmw 5 series g30 520d  specifications", tried)  # repeat
    assert not accept_ai_query("BMW 520d site:milanuncios.com precio", tried)  # deny-listed
    assert not accept_ai_query("x" * 201, tried)
    assert not accept_ai_query("   ", tried)


# --- spec 007 US5: short favourite identity, market words, retry, learned sources ----------------------------

from automind.domain.search_plan import retry_queries, short_identity  # noqa: E402

GOLF_R = Identity("Volkswagen", "Golf", "Mk8.5", "Golf Variant R 2.0 TSI 333 CV DSG 4MOTION")
BMW_T = Identity("BMW", "3 Series", "G21", "320d Touring M Sport Steptronic")


def test_short_identity_drops_generation_codes_repeats_and_gearbox_noise():
    assert short_identity(GOLF_R) == "Volkswagen Golf Variant R 333"
    assert short_identity(BMW_T) == "BMW 320d Touring"  # the engine code names the model
    assert short_identity(Identity("SEAT", "Ateca", "KH7", "1.5 EcoTSI 150 PS DSG")) == "SEAT Ateca 1.5 EcoTSI 150"
    assert short_identity(Identity("Toyota", "C-HR", None, "2.0 hybrid 197 CV")) == "Toyota C-HR 2.0 hybrid 197"
    tucson = Identity("Hyundai", "Tucson", "NX4", "1.6 T-GDi 150 PS MHEV")
    assert short_identity(tucson) == "Hyundai Tucson 1.6 T-GDi 150 MHEV"
    assert short_identity(Identity("Volkswagen", "Golf", "Mk8", "GTI 2.0 TSI 245 PS DSG")) == "Volkswagen Golf GTI 245"
    assert short_identity(Identity("Tesla", "Model 3", "Highland", "Performance AWD")) == "Tesla Model 3 Performance"
    for car in (GOLF_R, BMW_T):
        s = short_identity(car).lower().split()
        assert len(s) == len(set(s))
        assert not {"mk8.5", "g21", "dsg", "4motion", "steptronic", "cv"} & set(s)


def test_shorter_form_for_the_retry():
    assert short_identity(GOLF_R, level=1) == "Volkswagen Golf"
    assert short_identity(BMW_T, level=1) == "BMW 320d"


MARKET_T = {
    "reliability": "{short} fiabilidad problemas {sites}",
    "reliability@DE": "{short} Pannenstatistik Mängel {sites}",
    "reliability@EN": "{short} reliability problems {sites}",
}
REL_FAV = [
    {"domain": "motor.es", "areas": ["reliability"], "markets": ["ES"], "priority": 1},
    {"domain": "adac.de", "areas": ["reliability"], "markets": ["DE"], "priority": 1},
    {"domain": "whatcar.com", "areas": ["reliability"], "markets": ["EN"], "priority": 1},
]


def test_favourite_words_follow_the_market_language():
    qs = queries("reliability", GOLF_R, ["ES", "EN", "DE"], REL_FAV, MARKET_T, {}, 0)
    by = {q.market: q.text for q in qs}
    assert by["ES"] == "Volkswagen Golf Variant R 333 fiabilidad problemas site:motor.es"
    assert "Pannenstatistik" in by["DE"] and "fiabilidad" not in by["DE"]
    assert "reliability" in by["EN"]


def test_zero_hit_favourite_gets_one_shorter_retry():
    qs = queries("reliability", GOLF_R, ["DE"], REL_FAV, MARKET_T, {}, 0)
    again = retry_queries(qs, GOLF_R, MARKET_T)
    assert [q.kind for q in again] == ["FAVOURITE_RETRY"]
    assert again[0].text == "Volkswagen Golf Pannenstatistik Mängel site:adac.de"
    assert again[0].sites == qs[0].sites
    assert retry_queries(again, GOLF_R, MARKET_T) == []  # a retry is never retried


def test_learned_sources_join_round0_after_the_configured_ones():
    learned = {"DE": ["autobild.de", "adac.de", "milanuncios.com", "a.de", "b.de", "c.de", "d.de"]}
    qs = queries("reliability", GOLF_R, ["DE"], REL_FAV, MARKET_T, {}, 0, learned=learned, learned_per_area=4)
    assert qs[0].sites == ("adac.de",) and not qs[0].learned
    extra = [s for q in qs if q.learned for s in q.sites]
    assert extra == ["autobild.de", "a.de", "b.de", "c.de"]  # configured adac.de not repeated, denied dropped


def test_trim_codes_survive_and_generation_decimals_do_not():
    assert short_identity(Identity("BMW", "3 Series", "G20", "M340i xDrive")) == "BMW M340i"
    assert short_identity(Identity("Audi", "A3", "8Y", "RS3 Sportback 400 CV")) == "Audi A3 RS3 Sportback 400"
    assert short_identity(Identity("Volkswagen", "Golf", None, "Golf 8.5 R 333 CV")) == "Volkswagen Golf R 333"


def test_model_names_and_word_order_are_kept():
    rr = Identity("Land Rover", "Range Rover Sport", None, "HSE 4.4 V8 300 PS 6-speed automatic 4WD")
    assert short_identity(rr) == "Land Rover Range Rover Sport 4.4 300"
    assert short_identity(Identity("Audi", "Q3", None, "35 TFSI 150 CV S tronic")) == "Audi Q3 35 TFSI"
    rav4 = Identity("Toyota", "RAV4", "XA50", "2.5 Hybrid Dynamic Force 218hp")
    assert short_identity(rav4) == "Toyota RAV4 2.5 Hybrid"
    assert short_identity(Identity("BYD", "Seal U", None, "DM-i Boost 1.5 218 CV e-CVT")) == "BYD Seal U DM-i 1.5 218"
    assert short_identity(Identity("Lexus", "NX", None, "350h")) == "Lexus NX 350h"  # only BMW codes drop the model
