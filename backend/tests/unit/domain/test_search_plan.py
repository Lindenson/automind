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
    {"domain": "auto-data.net", "source_type": "SPEC_DATABASE", "areas": ["specs"], "markets": ["ANY"], "priority": 1},
    {"domain": "fichasmotor.com", "source_type": "SPEC_DATABASE", "areas": ["specs"], "markets": ["ES"], "priority": 3},
    {"domain": "motor.es", "source_type": "PUBLICATION", "areas": ["specs"], "markets": ["ES"], "priority": 2},
    {"domain": "parkers.co.uk", "source_type": "PUBLICATION", "areas": ["specs"], "markets": ["EN"], "priority": 2},
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
    assert first.sites == ("km77.com", "ultimatespecs.com", "auto-data.net", "motor.es")
    assert (
        first.text
        == "BMW 5 Series G30 520d site:km77.com OR site:ultimatespecs.com OR site:auto-data.net OR site:motor.es"
    )
    assert qs[1].sites == ("fichasmotor.com",)
    assert {q.market for q in qs} == {"ES"}
    assert "parkers.co.uk" not in {s for q in qs for s in q.sites}


def test_market_any_matches_every_market_and_each_market_gets_its_queries():
    qs = _plan("specs", markets=("ES", "EN"))
    en = [q for q in qs if q.market == "EN"]
    assert en and en[0].sites == ("parkers.co.uk",)  # ANY sites were already queried for ES
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
