"""Spec 008 US6 / FR-017 / SC-008: versions kept only when their documents support them; a second look-up of the
same generation within the freshness period makes no search."""

from types import SimpleNamespace

from automind.application import versions
from automind.application.versions import _V, VersionsOut

DOC = (
    "Skoda Octavia: versiones",
    "Gama Octavia 2024. 1.5 TSI 115 CV manual. 2.0 TDI 116 CV manual o DSG. 2.0 TDI 150 CV DSG, también 4x4.",
)
URL = "https://www.km77.com/octavia"


def _out(**kw: object) -> VersionsOut:
    base = {
        "generation": "Mk4",
        "generation_years_from": 2020,
        "generation_years_to": None,
        "versions": [
            _V(
                engine="2.0 TDI 116 CV",
                fuel="diesel",
                displacement_l=2.0,
                power_cv=116,
                gearboxes=["manual", "dct"],
                drives=["FWD"],
                excerpt="2.0 TDI 116 CV manual o DSG",
                source_url=URL,
            ),
            _V(
                engine="2.0 TDI 150 CV",
                fuel="diesel",
                power_cv=150,
                gearboxes=["dct"],
                drives=["FWD", "AWD"],
                excerpt="2.0 TDI 150 CV DSG",
                source_url=URL,
            ),
            _V(
                engine="2.0 TDI 200 CV", fuel="diesel", power_cv=200, excerpt="2.0 TDI 200 CV", source_url=URL
            ),  # no doc
            _V(engine="2.0 TDI 115 CV", fuel="diesel", power_cv=115, excerpt="2.0 TDI 116 CV manual", source_url=URL),
            _V(
                engine="1.9 TDI 105 CV",
                fuel="diesel",
                power_cv=105,
                years_from=2004,
                years_to=2012,
                excerpt="Gama Octavia 2024",
                source_url=URL,
            ),  # another generation
            _V(engine="2.0 TDI 116 CV", fuel="diesel", power_cv=116, excerpt="2.0 TDI 116 CV", source_url=URL),  # dup
            _V(engine="1.5 TSI 150 CV", fuel="petrol", power_cv=150, excerpt="1.5 TSI 150 CV", source_url="https://x"),
            _V(engine="1.5 TSI 115 CV", fuel="petrol", power_cv=115, excerpt="1.5 TSI 115 CV manual", source_url=URL),
        ],
    }
    return VersionsOut.model_validate({**base, **kw})


def test_validate_keeps_only_what_the_documents_support() -> None:
    kept = versions.validate(_out(), {URL: DOC})
    assert [v.engine for v in kept] == ["2.0 TDI 116 CV", "2.0 TDI 150 CV", "1.5 TSI 115 CV"]  # source order
    assert kept[0].engine_cc == 2000 and kept[1].engine_cc == 2000 and kept[1].power_kw == 110
    assert kept[0].excerpt == "2.0 TDI 116 CV manual o DSG" and kept[0].source_url == URL


class Store:
    def __init__(self) -> None:
        self.rows: dict[tuple[str, str, str], object] = {}

    async def get(self, make, model, generation, year, new, ttl_days):  # noqa: ANN001, ANN201
        return next((g for (mk, md, _), g in self.rows.items() if (mk, md) == (make, model)), None)

    async def put(self, g):  # noqa: ANN001, ANN201
        self.rows[(g.make, g.model, g.generation)] = g


async def test_second_look_up_in_the_freshness_period_makes_no_search() -> None:
    calls = {"search": 0, "llm": 0}

    async def search(q, **kw):  # noqa: ANN001, ANN003, ANN202
        calls["search"] += 1
        return [SimpleNamespace(url=URL)]

    async def get(url, **kw):  # noqa: ANN001, ANN003, ANN202
        return SimpleNamespace(url=URL, title=DOC[0], text=DOC[1])

    async def structured(role, schema, prompt, user):  # noqa: ANN001, ANN202
        calls["llm"] += 1
        assert role == "versions" and "<untrusted_document" in user
        return _out()

    ports = SimpleNamespace(
        versions=Store(),
        search=SimpleNamespace(search=search),
        page_store=SimpleNamespace(get=get),
        llm=SimpleNamespace(structured=structured),
        ref=SimpleNamespace(prompts={"versions": "p"}, search={"intake": {"versions_ttl_days": 60}}),
    )
    g = await versions.lookup(ports, "Skoda", "Octavia", generation="Mk4", year=None, new=True)  # type: ignore[arg-type]
    assert g is not None and len(g.versions) == 3 and g.sources == [{"url": URL, "name": DOC[0]}]
    again = await versions.lookup(ports, "Skoda", "Octavia", generation="Mk4", year=None, new=True)  # type: ignore[arg-type]
    assert again is g and calls == {"search": 2, "llm": 1}  # two queries (range, data sheet), one reading


async def test_no_store_no_ladder() -> None:
    ports = SimpleNamespace(versions=None, ref=SimpleNamespace(prompts={"versions": "p"}, search={}))
    assert await versions.lookup(ports, "Skoda", "Octavia", generation=None, year=None, new=True) is None  # type: ignore[arg-type]


async def test_a_list_of_one_or_two_versions_is_not_the_range() -> None:
    async def search(q, **kw):  # noqa: ANN001, ANN003, ANN202
        return [SimpleNamespace(url=URL)]

    async def get(url, **kw):  # noqa: ANN001, ANN003, ANN202
        return SimpleNamespace(url=URL, title=DOC[0], text=DOC[1])

    async def structured(role, schema, prompt, user):  # noqa: ANN001, ANN202
        return _out(versions=[_out().versions[0]])

    store = Store()
    ports = SimpleNamespace(
        versions=store,
        search=SimpleNamespace(search=search),
        page_store=SimpleNamespace(get=get),
        llm=SimpleNamespace(structured=structured),
        ref=SimpleNamespace(prompts={"versions": "p"}, search={}),
    )
    assert await versions.lookup(ports, "Audi", "A4", generation="B9", year=2023, new=False) is None  # type: ignore[arg-type]
    assert store.rows == {}  # not kept for other chats either


def test_range_pages_first_one_version_pages_last() -> None:
    from automind.application.versions import _rank

    one = "https://www.auto-data.net/es/skoda-octavia-iv-combi-rs-2.0-tsi-245hp-10693"
    data = "https://www.km77.com/coches/audi/a4/2016/4-puertas/estandar/a4-20-tdi-clean-diesel-150-cv/datos"
    gama = "https://www.km77.com/coches/skoda/octavia/2024/estandar/gama"
    assert _rank(gama, "Skoda") > _rank("https://www.amsconde.com/skoda-octavia", "Skoda") > _rank(one, "Skoda")
    assert _rank(data, "Audi") < 0


async def test_a_cached_list_that_does_not_cover_the_year_is_completed_for_it() -> None:
    from automind.domain.ladder import Generation, Version

    old = [
        Version(f"2.0 TDI {cv} CV", "diesel", 1968, kw, years_from=2015, years_to=2018, source_url="u")
        for cv, kw in ((122, 90), (150, 110), (190, 140))
    ]
    store = Store()
    await store.put(Generation("Audi", "A4", "B9", 2015, 2024, "SEDAN", old, []))
    facelift = "A4 2019-2024: 35 TDI 163 CV, 40 TDI 204 CV, 35 TFSI 150 CV."

    async def search(q, **kw):  # noqa: ANN001, ANN003, ANN202
        assert "B9 2023" in q
        return [SimpleNamespace(url=URL)]

    async def get(url, **kw):  # noqa: ANN001, ANN003, ANN202
        return SimpleNamespace(url=URL, title="A4", text=facelift)

    async def structured(role, schema, prompt, user):  # noqa: ANN001, ANN202
        return VersionsOut(
            generation="B9",
            versions=[
                _V(engine=e, fuel=f, power_cv=cv, years_from=2019, years_to=2024, excerpt=x, source_url=URL)
                for e, f, cv, x in (
                    ("35 TDI 163 CV", "diesel", 163, "35 TDI 163 CV"),
                    ("40 TDI 204 CV", "mhev", 204, "40 TDI 204 CV"),
                    ("35 TFSI 150 CV", "petrol", 150, "35 TFSI 150 CV"),
                )
            ],
        )

    ports = SimpleNamespace(
        versions=store,
        search=SimpleNamespace(search=search),
        page_store=SimpleNamespace(get=get),
        llm=SimpleNamespace(structured=structured),
        ref=SimpleNamespace(prompts={"versions": "p"}, search={}),
    )
    g = await versions.lookup(ports, "Audi", "A4", generation="B9", year=2023, new=False)  # type: ignore[arg-type]
    assert g is not None and len(g.versions) == 6
    assert versions.covers(g, 2023) and versions.covers(g, 2016)
