"""Spec 011 T108 (closes 010 T065): the scout's pure helpers — gaps, queries in the market's language, the code
check of the reworded queries, new domains from hits, the path-prefix locator and the budget left."""

from __future__ import annotations

from automind.acquisition.agents import scout
from automind.shared.research_order.search_plan import Identity

SEARCH = {"default_markets": ["ES", "EN"], "area_markets": {"used_price": ["ES", "DE", "US"], "measured": ["DE"]}}
CAR = Identity("SEAT", "León", "Mk4", "1.5 TSI 150", "2020-")


def test_area_markets_from_search_yaml_and_prices_only_in_europe() -> None:
    assert scout.area_markets(SEARCH, "specs") == ["ES", "EN"]
    assert scout.area_markets(SEARCH, "measured") == ["DE"]
    assert scout.area_markets(SEARCH, "used_price") == ["ES", "DE"]  # US dropped: prices only for Europe
    assert scout.area_markets({"area_markets": {"price": ["JP"]}}, "price") == []


def test_gaps_are_no_data_outcomes_or_too_few_active_sources() -> None:
    jobs = [
        scout.Job("specs", "v1", 0),
        scout.Job("specs", "v1", 0),
        scout.Job("specs", "v2", 3),
        scout.Job("measured", "v3", 2),
        scout.Job("reviews", "v4", 5),
    ]
    active = {("specs", "ES"): 3, ("specs", "EN"): 3, ("measured", "DE"): 1, ("reviews", "ES"): 2, ("reviews", "EN"): 4}
    gaps = scout.find_gaps(jobs, active, SEARCH, min_active=2)
    keys = [g.key for g in gaps]
    # no-data first (most outcomes), then the fewest active; a well-covered area with values is no gap
    assert keys == ["specs|ES", "specs|EN", "measured|DE"]
    g = gaps[0]
    assert (g.nodata, g.active, g.variant_id) == (2, 3, "v1")  # the popular variant with the gap
    assert "2 no-data outcomes" in g.reason
    m = gaps[2]
    assert (m.nodata, m.active, m.variant_id) == (0, 1, "v3")
    assert "1 active source" in m.reason and "minimum 2" in m.reason


def test_gaps_skip_areas_without_open_templates_and_markets_outside_europe_for_prices() -> None:
    jobs = [scout.Job("used_price", "v1", 0), scout.Job("specs", "v2", 0)]
    gaps = scout.find_gaps(jobs, {}, SEARCH, min_active=2, areas={"used_price"})
    assert [g.key for g in gaps] == ["used_price|ES", "used_price|DE"]


def test_queries_from_open_templates_in_the_market_and_bounded() -> None:
    tpl = ["{make} {model} {generation} {variant} ficha técnica", "{make} {model} {generation} {variant} specs",
           "{make} {model} ficha técnica {sites}", "{make} {model} {generation} {variant} ficha técnica"]  # fmt: skip
    qs = scout.build_queries(tpl, CAR, "DE", {"DE": "Leon"}, limit=5)
    assert qs == ["SEAT Leon Mk4 1.5 TSI 150 ficha técnica", "SEAT Leon Mk4 1.5 TSI 150 specs"]  # no {sites}, deduped
    assert scout.build_queries(tpl, CAR, "ES", {}, limit=1) == ["SEAT León Mk4 1.5 TSI 150 ficha técnica"]
    assert scout.build_queries(tpl, CAR, "ES", {}, limit=0) == []


def test_reworded_queries_are_checked_by_code() -> None:
    orig = ["SEAT León ficha técnica", "SEAT León prueba", "SEAT León opinión", "SEAT León fiabilidad"]
    proposed = [
        "SEAT León technische Daten",  # fine
        "SEAT León Test site:mobile.de",  # operator: rejected
        "VW Golf Test",  # make lost: rejected
        "x" * 250 + " SEAT",  # too long: rejected
    ]
    assert scout.checked_rewording(orig, proposed, "SEAT") == [
        "SEAT León technische Daten",
        "SEAT León prueba",
        "SEAT León opinión",
        "SEAT León fiabilidad",
    ]
    assert scout.checked_rewording(orig, proposed[:2], "SEAT") == orig  # a different count: the templates stand


def test_found_domains_skip_known_denied_and_bounded() -> None:
    hits = [
        ("https://www.km77.com/fichas/seat/leon", "SEAT León ficha"),
        ("https://www.wallapop.com/item/seat-leon", "SEAT León"),  # deny-listed classifieds
        ("https://new-specs.example/fichas/seat-leon-15-tsi", "SEAT León 1.5 TSI"),
        ("https://new-specs.example/fichas/other", "dup"),
        ("https://another.example/a", "a"),
        ("https://third.example/b", "b"),
    ]
    got = scout.found_domains(hits, known={"km77.com"}, deny=("wallapop.com",), limit=2)
    assert [(f.domain, f.url, f.rank) for f in got] == [
        ("new-specs.example", "https://new-specs.example/fichas/seat-leon-15-tsi", 3),
        ("another.example", "https://another.example/a", 5),
    ]


def test_path_prefix_locator_needs_three_examples() -> None:
    urls = [
        "https://www.km77.com/coches/seat/leon/2020/ficha-1",
        "https://km77.com/coches/seat/ibiza/2021/ficha-2?x=1",
        "https://www.km77.com/coches/bmw/serie-3/2019/ficha-3",
        "https://www.km77.com/precios/seat",
    ]
    assert scout.path_prefixes(urls) == ["/coches/"]
    assert scout.path_prefixes(urls[:2]) == []  # two examples are not a pattern
    deep = [f"https://a.example/fichas/tecnicas/{i}" for i in range(4)] + ["https://a.example/fichas/x/1"]
    assert scout.path_prefixes(deep) == ["/fichas/"]  # the prefix that covers most accepted pages
    assert scout.path_prefixes([f"https://a.example/p{i}" for i in range(5)]) == []  # root pages: no prefix


def test_budget_left_is_the_smaller_of_the_scout_and_discovery_budgets() -> None:
    assert scout.budget_left(0.10, 0.02, 0.20, 0.15) == 0.05
    assert scout.budget_left(0.10, 0.02, 0.20, 0.0) == 0.08
    assert scout.budget_left(0.10, 0.20, 0.20, 0.0) == 0.0


def test_sample_journal_reason() -> None:
    gap = scout.Gap("specs", "ES", 2, 1, "v1", "")
    r = scout.addition_reason(gap, "SEAT León ficha técnica", 3)
    assert r == 'scout: gap specs/ES (2 no-data outcomes, 1 active); hit #3 of "SEAT León ficha técnica"'
