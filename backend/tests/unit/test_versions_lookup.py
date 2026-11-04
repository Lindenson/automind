"""Spec 008 US6 / FR-017 / SC-008: versions kept only when their documents support them; a second look-up of the
same generation within the freshness period makes no search."""

from types import SimpleNamespace

from automind.application import versions
from automind.application.versions import _V, VersionsOut

DOC = ("Skoda Octavia: versiones", "Gama Octavia 2024. 2.0 TDI 116 CV manual o DSG. 2.0 TDI 150 CV DSG, también 4x4.")
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
        ],
    }
    return VersionsOut.model_validate({**base, **kw})


def test_validate_keeps_only_what_the_documents_support() -> None:
    kept = versions.validate(_out(), {URL: DOC})
    assert [v.engine for v in kept] == ["2.0 TDI 116 CV", "2.0 TDI 150 CV"]  # source order: the base first
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
    assert g is not None and len(g.versions) == 2 and g.sources == [{"url": URL, "name": DOC[0]}]
    again = await versions.lookup(ports, "Skoda", "Octavia", generation="Mk4", year=None, new=True)  # type: ignore[arg-type]
    assert again is g and calls == {"search": 1, "llm": 1}


async def test_no_store_no_ladder() -> None:
    ports = SimpleNamespace(versions=None, ref=SimpleNamespace(prompts={"versions": "p"}, search={}))
    assert await versions.lookup(ports, "Skoda", "Octavia", generation=None, year=None, new=True) is None  # type: ignore[arg-type]
