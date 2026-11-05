"""Live chats 5821ac77 / d7edfc29 / 2f8b0018: a NEW Kia Sorento PHEV was identified as "1.6 T-GDi 265 CV, 2020–"
from an old catalog row although the 2024 facelift sells 288 CV ("list of versions not found in sources").

B1. For a new car the versions look-up tries harder before falling back: the generation with the current year, the
    market's model name, the registry's spec sources.
B2. Falling back to catalog rows, a new car never takes a row a newer row of the same engine supersedes; when only
    stale rows exist, the version is marked uncertain and asked once instead of silently taking the old one.
"""

from __future__ import annotations

import re
from types import SimpleNamespace

from automind.application import identify, resolve, versions
from automind.application.versions import _V, VersionsOut
from automind.domain.casefile import CaseCar, CaseFile, Constraints
from automind.domain.identity import parse_engine
from automind.infrastructure.config import reference
from automind.orchestration.prompts import load_all

NOW = 2026
RANGE_2026 = "https://www.km77.com/coches/firstkia/sorento/2026/gama"
RANGE_SITE = "https://www.fichas.example/firstkia-sorento-2026"
DOC_2026 = (
    "Firstkia Sorento 2026: precios y gama",
    "Gama Sorento 2026 (renovado en 2024): 1.6 T-GDi HEV 215 CV, 1.6 T-GDi PHEV 288 CV, 2.2 CRDi 193 CV.",
)


class Store:
    def __init__(self) -> None:
        self.rows: dict[tuple[str, str, str], object] = {}

    async def get(self, make, model, generation, year, new, ttl_days):  # noqa: ANN001, ANN201
        return self.rows.get((make, model, generation or ""))

    async def put(self, g):  # noqa: ANN001, ANN201
        self.rows[(g.make, g.model, g.generation)] = g


class Registry:
    def __init__(self) -> None:
        self.asked: list[tuple[str, list[str]]] = []

    async def sources_for(self, area, markets, limit):  # noqa: ANN001, ANN201
        self.asked.append((area, list(markets)))
        return [SimpleNamespace(domain="fichas.example", market="ES")]


def _ports(make: str) -> tuple[SimpleNamespace, list[str]]:
    queries: list[str] = []

    async def search(q, **kw):  # noqa: ANN001, ANN003, ANN202
        queries.append(q)
        if "site:fichas.example" in q:
            return [SimpleNamespace(url=RANGE_SITE)]
        if str(NOW) in q:  # only the current year's pages list the facelift's range
            return [SimpleNamespace(url=RANGE_2026)]
        return []  # the generation alone: nothing (live: "list of versions not found in sources")

    async def get(url, **kw):  # noqa: ANN001, ANN003, ANN202
        return SimpleNamespace(url=url, title=DOC_2026[0], text=DOC_2026[1])

    async def structured(role, schema, prompt, user):  # noqa: ANN001, ANN202
        assert role == "versions"
        url = re.search(r'url="([^"]+)"', user).group(1)
        return VersionsOut(
            generation="MQ4", generation_years_from=2020, generation_years_to=None, body_class="SUV",
            versions=[
                _V(engine=e, fuel=f, displacement_l=d, power_cv=cv, years_from=2024, excerpt=e, source_url=url,
                   gearboxes=["automatic"], drives=["AWD"])
                for e, f, d, cv in (("1.6 T-GDi HEV 215 CV", "hybrid", 1.6, 215),
                                    ("1.6 T-GDi PHEV 288 CV", "phev", 1.6, 288),
                                    ("2.2 CRDi 193 CV", "diesel", 2.2, 193))
            ],
        )  # fmt: skip

    ref = reference(load_all())
    ports = SimpleNamespace(
        ref=ref, versions=Store(), registry=Registry(), search=SimpleNamespace(search=search),
        page_store=SimpleNamespace(get=get), llm=SimpleNamespace(structured=structured),
    )  # fmt: skip
    return ports, queries


async def test_new_car_versions_look_up_tries_the_current_year_and_registry_spec_sources(migrated) -> None:
    ports, queries = _ports("Firstkia")
    g = await versions.lookup(ports, "Firstkia", "Sorento", generation="MQ4", year=None, new=True,  # type: ignore[arg-type]
                              current_year=NOW)  # fmt: skip
    assert g is not None, queries
    assert "1.6 T-GDi PHEV 288 CV" in {v.engine for v in g.versions}
    assert any("MQ4" in q and str(NOW) in q for q in queries), queries
    assert any("site:fichas.example" in q for q in queries), queries
    assert ports.registry.asked and ports.registry.asked[0][0] == "specs"
    assert len(queries) <= 2 + versions.HARDER_QUERIES  # bounded: two first searches, then a few more


async def test_new_sorento_phev_identified_from_the_current_range_not_an_old_row(migrated) -> None:
    ports, _ = _ports("Firstkia")
    hint = Constraints(generation_hint="MQ4", engine_hint=parse_engine("PHEV"))
    car = CaseCar(key="car#1", request_text="Firstkia Sorento PHEV nuevo", make="Firstkia", model="Sorento",
                  condition="NEW", constraints=hint)  # fmt: skip
    o = await identify._ladder(ports, CaseFile(cars=[car]), car, NOW)  # type: ignore[arg-type]
    assert o is not None and o.outcome == "IDENTIFIED", o
    assert "288" in (car.label or "") and car.ladder is not None and car.ladder.certainty == "SOURCED"


async def _rows(make: str, rows: list[tuple[str, str, int, int]]) -> None:
    from automind.infrastructure import db

    await db.init_db()
    for name, gen, since, kw in rows:
        ident = resolve.VariantIdentity(make=make, model="Sorento", generation=gen, variant_name=name,
                                        powertrain="PHEV", body_class="SUV", generation_years_from=since,
                                        generation_years_to=None, engine_cc=1598, power_kw=kw, fuel="phev",
                                        certainty="exact")  # fmt: skip
        await resolve.upsert_variant(ident, reference({}))


def _new_sorento(make: str) -> CaseCar:
    return CaseCar(key="car#1", request_text=f"{make} Sorento PHEV nuevo", make=make, model="Sorento",
                   condition="NEW", constraints=Constraints(engine_hint=parse_engine("PHEV")))  # fmt: skip


async def test_fallback_never_takes_a_row_a_newer_row_of_the_same_engine_supersedes(migrated) -> None:
    make = "Supersedekia"
    await _rows(make, [("1.6 T-GDi PHEV 265 CV", "MQ4", 2020, 195), ("1.6 T-GDi PHEV 288 CV", "MQ4 PE", 2024, 212)])
    ports = SimpleNamespace(ref=reference(load_all()), versions=None)
    car = _new_sorento(make)
    o = await identify._fallback(ports, CaseFile(cars=[car]), car, NOW, None)  # type: ignore[arg-type]
    assert o.outcome == "IDENTIFIED", o
    assert "288" in (car.label or "") and "265" not in (car.label or "")
    assert car.ladder is not None and car.ladder.certainty == "LESS_CERTAIN"


async def test_fallback_with_only_a_stale_row_asks_once_instead_of_taking_it(migrated) -> None:
    make = "Stalekia"
    await _rows(make, [("1.6 T-GDi PHEV 265 CV", "MQ4", 2020, 195)])
    ports = SimpleNamespace(ref=reference(load_all()), versions=Store())  # the look-up ran and found no list
    car = _new_sorento(make)
    case = CaseFile(cars=[car])
    o = await identify._fallback(ports, case, car, NOW, None)  # type: ignore[arg-type]
    assert o.outcome == "CHOICES" and o.need == "POWER", o  # one question, never silently the 2020 row
    assert car.variant_id is None
    assert [c.label for c in o.choices] == ["1.6 T-GDi PHEV 265 CV"]
    assert any(e["kind"] == "version_uncertain" for e in o.events), o.events
    case.intake.bump(car.key, "POWER")  # asked once: the row is taken, less certain, never asked again
    o = await identify._fallback(ports, case, car, NOW, None)  # type: ignore[arg-type]
    assert o.outcome == "IDENTIFIED" and "265" in (car.label or ""), o
    assert car.resolution == "PROPOSED" and {"kind": "identity_less_certain"} in o.events
