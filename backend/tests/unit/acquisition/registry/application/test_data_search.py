"""Closing data holes (live chat 5821ac77): `site:` queries to the registry's sources, escalation to the other
European markets in a follow-up round, used-car queries with the model year and the market's model name, and
whole-generation used-price ranges rejected for a car with a year."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from automind.acquisition.pipeline.domain.items import ExcerptCounter
from automind.acquisition.pipeline.domain.used_prices import used_prices
from automind.acquisition.registry.application.service import RegistryService, rank_queryable
from automind.chat.domain.identification import used
from automind.shared.infrastructure.config import loader as config
from automind.shared.research_order import plan as research_plan
from automind.shared.research_order import search_plan
from automind.shared.research_order.search_plan import Identity
from automind.shared.vehicle.identity import Aliases

PRADO_2010 = Identity("Toyota", "Land Cruiser Prado", "J150", "3.0 D-4D 190", "2010")
SORENTO = Identity("Kia", "Sorento", "MQ4", "1.6 T-GDi PHEV 265 AWD", "2020-")
NAMES = {"ES": "Land Cruiser", "DE": "Land Cruiser"}


# --- 1. registry `site:` queries ---------------------------------------------------------------------------------


def test_registry_queries_group_sites_per_market_skip_favourites_denied_and_junk() -> None:
    sources = [
        ("km77.com", "ES"),  # already a favourite query: skipped
        ("motor.es", "ES"),
        ("autoscout24.de", "DE"),  # deny-listed classifieds: never
        ("aci.gov.it (ex aci.it)", "IT"),  # survey text, not a domain: never
        ("adac.de", "DE"),
        ("dat.de", "DE"),
        ("autobild.de", "DE"),
        ("auto-motor-und-sport.de", "DE"),
        ("quattroruote.it", "IT"),
    ]
    out = search_plan.registry_queries(
        "price", SORENTO, sources, {}, exclude=["km77.com"], domains_per_query=3, max_queries=3
    )
    assert [q.kind for q in out] == ["REGISTRY"] * 3
    assert [(q.market, q.sites) for q in out] == [
        ("ES", ("motor.es",)),
        ("DE", ("adac.de", "dat.de", "autobild.de")),
        ("DE", ("auto-motor-und-sport.de",)),
    ]  # bounded: the Italian source waits for another round
    assert out[1].text == "Kia Sorento 1.6 T-GDi PHEV 265 site:adac.de OR site:dat.de OR site:autobild.de"


def test_registry_query_template_per_area_and_market_name_and_year() -> None:
    t = {"registry": "{short} {sites}", "registry:used_price": "{make} {model} {years} {sites}"}
    out = search_plan.registry_queries(
        "used_price", PRADO_2010, [("motor.es", "ES"), ("dat.de", "DE"), ("autoexpress.co.uk", "EN")], t,
        market_names=NAMES,
    )  # fmt: skip
    assert [q.text for q in out] == [
        "Toyota Land Cruiser 2010 site:motor.es",
        "Toyota Land Cruiser 2010 site:dat.de",
        "Toyota Land Cruiser Prado 2010 site:autoexpress.co.uk",
    ]
    assert search_plan.registry_queries("price", SORENTO, [("motor.es", "ES")], t, max_queries=0) == []


# --- 2. escalation in a follow-up round --------------------------------------------------------------------------


def test_registry_markets_round0_own_then_other_europe_and_beyond_except_prices() -> None:
    assert research_plan.registry_markets("price", ["ES", "EN"], 0) == ["ES", "EN", "ANY"]
    r1 = research_plan.registry_markets("price", ["ES", "EN"], 1)
    assert r1[:5] == ["DE", "FR", "IT", "PT", "NL"] and "ES" not in r1 and "ANY" not in r1
    assert not set(r1) & set(research_plan.OUTSIDE_EUROPE)  # prices come from European markets only (FR-009)
    rel = research_plan.registry_markets("reliability", ["ES", "EN", "DE"], 1)
    assert rel.index("FR") < rel.index("US") and "JP" in rel and "DE" not in rel
    assert research_plan.registry_markets("incentives", ["ES"], 0) == []  # the user's own market only


def test_unmet_area_gets_a_follow_up_round_within_the_depth() -> None:
    p = research_plan.ResearchPlan([research_plan.Job("A", "v", "price"), research_plan.Job("A", "v", "specs")], 1)
    gaps = research_plan.gaps(p, {("A", "price"): False, ("A", "specs"): True}, 0)
    assert [(j.area, j.round) for j in gaps] == [("price", 1)]
    assert research_plan.gaps(p, {("A", "price"): False}, 1) == []  # the depth bound holds


class _Store:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.asked: list[tuple[str, list[str]]] = []

    async def queryable(self, area: str, markets: list[str]) -> list[dict[str, Any]]:
        self.asked.append((area, markets))
        return [r for r in self.rows if r["market"] in markets]


def _row(domain: str, status: str, market: str = "ES", score: float = 0.0, access: str = "ok") -> dict[str, Any]:
    return {"domain": domain, "status": status, "market": market, "score": score, "priority_seed": None,
            "access": access}  # fmt: skip


async def test_sources_for_active_by_score_then_candidates_whatever_the_autonomy() -> None:
    rows = [
        _row("cand.example", "candidate", score=0.9),
        _row("low.example", "active", score=0.1),
        _row("high.example", "active", score=0.8),
        _row("forbid.example", "active", score=1.0, access="terms_forbid"),
        _row("unknown.example", "candidate", access="unknown"),  # never surveyed: not queried
        _row("de.example", "candidate", market="DE"),
    ]
    svc = RegistryService(_Store(rows), {"autonomy": False})
    got = await svc.sources_for("price", ["ES", "DE"], 10)
    assert [s.domain for s in got] == ["high.example", "low.example", "cand.example", "de.example"]
    assert [s.unverified for s in got] == [False, False, True, True]
    assert [s.domain for s in rank_queryable(rows, ["DE", "ES"], 2)] == ["high.example", "low.example"]
    assert await svc.sources_for("price", ["ES"], 0) == []


# --- 3. used-car queries carry the year and the market's model name ---------------------------------------------


def test_used_prado_j150_queries_carry_year_and_market_model_name() -> None:
    fav = [
        {"domain": "km77.com", "areas": ["used_price"], "markets": ["ES"], "priority": 1},
        {"domain": "autoexpress.co.uk", "areas": ["used_price"], "markets": ["EN"], "priority": 1},
    ]
    t = config.favourite_queries()
    out = search_plan.queries("used_price", PRADO_2010, ["ES", "EN"], fav, t, {}, 0, market_names=NAMES)
    by_market = {q.market: q.text for q in out}
    assert by_market["ES"] == "Toyota Land Cruiser 2010 precio segunda mano site:km77.com"
    assert by_market["EN"] == "Toyota Land Cruiser Prado 2010 used price site:autoexpress.co.uk"
    opened = search_plan.queries("used_price", PRADO_2010, ["ES"], fav, t, config.open_queries(), 1,
                                 market_names=NAMES)  # fmt: skip
    assert opened[0].text.startswith("Toyota Land Cruiser 2010 segunda mano")
    assert all("J150" in q.text or "2010" in q.text for q in opened)  # the year or the generation, always
    empty = [search_plan.PlannedQuery("x", "FAVOURITE", "specs", "ES", ("km77.com",))]
    retry = search_plan.retry_queries(empty, PRADO_2010, t, NAMES)
    assert retry[0].text == "Toyota Land Cruiser ficha técnica site:km77.com"


def test_market_names_from_config_with_generation_override() -> None:
    a = Aliases.from_config(config.aliases())
    names = search_plan.market_names_of(a.market_names, "Toyota", "Land Cruiser Prado", "J150")
    assert names["ES"] == "Land Cruiser" and "EN" not in names
    cfg = {"A|B": {"ES": "B1"}, "A|B|G2": {"ES": "B2"}}
    assert search_plan.market_names_of(cfg, "A", "B", "G2") == {"ES": "B2"}
    assert search_plan.market_names_of(cfg, "A", "B", None) == {"ES": "B1"}
    assert search_plan.for_market(PRADO_2010, "FR", names) is PRADO_2010


def test_config_registry_templates_and_open_used_price_sources() -> None:
    t = config.favourite_queries()
    assert t["registry"] == "{short} {sites}" and t["registry:used_price"] == "{make} {model} {years} {sites}"
    favs = {f["domain"]: f for f in config.favourites()}  # validated: none of them is deny-listed
    assert "used_price" in favs["motor.es"]["areas"] and favs["dat.de"]["markets"] == ["DE"]
    assert "DE" in config.search_config()["area_markets"]["used_price"]


# --- 4. a whole-generation range never stands for one model year ------------------------------------------------


def test_whole_generation_range_is_not_the_price_of_one_year() -> None:
    assert used.whole_generation(2009, 2023, 2016)
    assert not used.whole_generation(2016, 2017, 2016)
    assert not used.whole_generation(2009, 2023, None)  # no year: a generation price is all there is
    assert not used.whole_generation(None, None, 2016)
    rs = [used.UsedRange(12000, 18000, 2009, 2023, "gen"), used.UsedRange(30000, 34000, 2016, 2016, "year")]
    p = used.used_price_for(rs, 2016)
    assert p is not None and p.url == "year"
    assert used.used_price_for(rs[:1], 2016) is None


def test_used_prices_rejects_whole_generation_range_for_a_car_with_a_year() -> None:
    text = "Toyota Land Cruiser 2009-2023: de 12.000 a 18.000 euros. Un Land Cruiser de 2016 cuesta 30.000-34.000 €."
    out = SimpleNamespace(ranges=[
        SimpleNamespace(min=12000, max=18000, currency="EUR", model_year_from=2009, model_year_to=2023,
                        market="ES", quoted_on=None, excerpt="de 12.000 a 18.000 euros"),
        SimpleNamespace(min=30000, max=34000, currency="EUR", model_year_from=2016, model_year_to=2016,
                        market="ES", quoted_on=None, excerpt="cuesta 30.000-34.000 €"),
    ])  # fmt: skip
    k = ExcerptCounter(text)
    rows = list(used_prices(SimpleNamespace(id="v"), out, k, {"EUR": 1.0}, car_year=2016))
    assert [r.status for r in rows] == ["REJECTED_OTHER_YEAR", "ACCEPTED"]
    assert (k.accepted, k.rejected) == (1, 1)
    rows = list(used_prices(SimpleNamespace(id="v"), out, ExcerptCounter(text), {"EUR": 1.0}))
    assert [r.status for r in rows] == ["ACCEPTED", "ACCEPTED"]  # no year: the generation range is kept
