"""Chat 8c6a2a58 (spec 008 live run): the used A4 got no used price and no warranty because the planner never
researched the used price of a used car, and brand pages (warranty, network) were dropped by the per-version
relevance gate."""

from datetime import UTC, datetime

from automind.acquisition.domain import relevance as rel
from automind.shared.research_order import search_plan
from automind.shared.research_order.plan import BRAND_AREAS, CarToPlan, areas_for, plan

IDENT = search_plan.Identity("Audi", "A4", "B9", "35 TFSI 150 CV", "2015-")
TEMPLATES = {"manufacturer_warranty": "{make} garantía oficial años kilómetros España"}


def test_a_used_car_researches_its_used_price_and_the_brand_warranty():
    for persona in ("BUYER", "PERFORMANCE", "EXPERT", "UNKNOWN"):
        assert {"used_price", "used_issues", "manufacturer"} <= areas_for(persona, [], "USED")
    assert "used_price" not in areas_for("BUYER", [], "NEW")
    p = plan([CarToPlan("car#2", "v2", "USED")], persona="PERFORMANCE", criteria=[], depth="QUICK",
             last_done={}, now=datetime(2026, 11, 5, tzinfo=UTC))  # fmt: skip
    assert {"used_price", "manufacturer"} <= {j.area for j in p.jobs}


def test_a_brand_page_is_judged_by_the_make_not_by_the_version():
    assert "manufacturer" in BRAND_AREAS
    page = rel.PageFacts("https://www.audi.es/es/web/es/servicio/garantia.html", "Garantía Audi",
                         "Todos los Audi nuevos tienen 2 años de garantía sin límite de kilómetros.")  # fmt: skip
    assert rel.judge_brand(page, "Audi").verdict == "RELEVANT"
    skoda = rel.PageFacts("https://example.es/x", "Garantía", "Škoda ofrece 2 años de garantía.")
    assert rel.judge_brand(skoda, "Skoda").verdict == "RELEVANT"
    other = rel.PageFacts("https://example.es/y", "Garantía BMW", "BMW ofrece 2 años de garantía.")
    assert rel.judge_brand(other, "Audi").verdict == "NOT_ABOUT_CAR"
    audit = rel.PageFacts("https://example.es/z", "Audit report", "An audited company.")
    assert rel.judge_brand(audit, "Audi").verdict == "NOT_ABOUT_CAR"


def test_the_warranty_is_searched_in_the_first_round_of_the_manufacturer_area_only():
    q = search_plan.warranty_query([], "manufacturer", 0, IDENT, TEMPLATES)
    assert [x.text for x in q] == ["Audi garantía oficial años kilómetros España"]
    assert search_plan.warranty_query([], "manufacturer", 1, IDENT, TEMPLATES) == []
    assert search_plan.warranty_query([], "price", 0, IDENT, TEMPLATES) == []
    assert search_plan.warranty_query(q, "manufacturer", 0, IDENT, TEMPLATES) == []


WARRANTY_URL = "https://www.garantias-coches.example/audi"
FAVOURITES = ("autovista24.autovistagroup.com", "jato.com", "ganvam.es", "anfac.com", "motor.es", "motorpasion.com",
              "diariomotor.com", "focus2move.com")  # fmt: skip


class _Web:
    """Every analyst page is blocked by robots; the warranty search finds the brand's page."""

    def __init__(self) -> None:
        self.read: list[str] = []

    async def search(self, query, *, market="ES", area=None, fresh=False):
        from automind.shared.contracts.web import SearchHit

        if "garantía oficial" in query:
            return [SearchHit(WARRANTY_URL, "Garantía Audi", "", 1)]
        return [SearchHit(f"https://{d}/audi-{abs(hash(query))}", "x", "", i) for i, d in enumerate(FAVOURITES, 1)]

    async def get(self, url, *, area=None):
        from automind.shared.contracts.web import Page

        self.read.append(url)
        if url == WARRANTY_URL:
            return Page(url=url, title="Garantía Audi", text="Audi: 2 años de garantía sin límite de km.")
        return None

    def last_reason(self, url):
        return "robots.txt disallows"


async def test_blocked_analyst_sites_never_crowd_out_the_warranty_page():
    from types import SimpleNamespace

    from automind.acquisition.pipeline import searches
    from automind.acquisition.pipeline.contracts import JobSpec
    from automind.chat.dialog.prompts import load_all
    from automind.delivery.bootstrap import reference

    web = _Web()
    ports = SimpleNamespace(search=web, page_store=web, ref=reference(load_all()))
    v = SimpleNamespace(make="Audi", model="A4", generation="B9", variant_name="35 TFSI 150 CV",
                        generation_years_from=2015, generation_years_to=None, powertrain="MHEV")  # fmt: skip
    job = JobSpec("j", "v", "manufacturer")

    async def emit(*_):
        return None

    _, pages, _ = await searches.pages_for(ports, v, job, [], set(), emit)  # type: ignore[arg-type]
    assert [p.url for p in pages] == [WARRANTY_URL]


def test_the_used_price_is_searched_for_the_car_s_model_year():
    from types import SimpleNamespace

    from automind.acquisition.pipeline import plan
    from automind.chat.dialog.prompts import load_all
    from automind.delivery.bootstrap import reference

    ports = SimpleNamespace(ref=reference(load_all()))
    v = SimpleNamespace(make="Audi", model="A4", generation="B9", variant_name="35 TFSI 150 CV",
                        generation_years_from=2015, generation_years_to=None, powertrain="MHEV")  # fmt: skip
    texts = [q.text for q in plan.queries_for(ports, v, "used_price", 0, [], car_year=2023)]  # type: ignore[arg-type]
    assert texts and all("2023" in t and "2015" not in t for t in texts)
    opened = [q.text for q in plan.queries_for(ports, v, "used_price", 1, [], car_year=2023)]  # type: ignore[arg-type]
    assert any("2023" in t for t in opened)
