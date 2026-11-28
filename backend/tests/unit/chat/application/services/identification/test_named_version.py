"""Spec 017 V2 (chat 725e7437): a version the person names that the sourced list lacks is searched for on its own
before anyone says it does not exist; what is found is added to the cached list; one search per generation."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from automind.acquisition.api import VersionEntry, VersionsOut, VersionsRead
from automind.acquisition.identity_readers.web import _rank, _richest
from automind.chat.application.services.identification import named_version
from automind.chat.domain.identification.ladder import Generation, Version, Wanted
from automind.shared.infrastructure.config.loader import load_yaml

DEALER = "https://caetano.es/bmw/coches-nuevos/serie-3/"
KM77 = "https://www.km77.com/coches/bmw/serie-3/2019/berlina/estandar/320d-berlina-aut2/datos"


def _v(engine: str, fuel: str, kw: int) -> Version:
    return Version(engine=engine, fuel=fuel, engine_cc=2000, power_kw=kw, source_url=DEALER, excerpt=engine)


LIST = Generation("BMW", "3 Series", "G20", 2019, None, "SEDAN",
                  [_v("318d 150 CV", "diesel", 110), _v("320i 184 CV", "petrol", 135),
                   _v("330e 292 CV", "phev", 215)], [{"url": DEALER, "name": "Caetano"}])  # fmt: skip
NAMED_320D = Wanted(fuel="diesel", family="320d", power_kw=140)


class _Acq:
    def __init__(self, entries: list[VersionEntry], doc: str) -> None:
        self.entries, self.doc, self.calls = entries, doc, []  # type: list[dict[str, Any]]

    async def versions(self, make: str, model: str, generation: str | None, **kw: Any) -> VersionsRead:
        self.calls.append(kw)
        out = VersionsOut(generation="G20", generation_years_from=2019, versions=self.entries)
        return VersionsRead(docs={KM77: ("BMW 320d Berlina", self.doc)}, out=out)


class _Store:
    def __init__(self) -> None:
        self.put_rows: list[Generation] = []

    async def put(self, g: Generation) -> None:
        self.put_rows.append(g)


def _ports(acq: _Acq | None) -> Any:
    ref = SimpleNamespace(search={"intake": load_yaml("search.yaml")["intake"]}, prompts={"versions": ""})
    return SimpleNamespace(acquisition=acq, versions=_Store(), ref=ref)


def _entry(engine: str, excerpt: str, cv: int) -> VersionEntry:
    return VersionEntry(engine=engine, fuel="diesel", displacement_l=2.0, power_cv=cv, excerpt=excerpt,
                        source_url=KM77)  # fmt: skip


def test_the_list_lacks_the_named_320d() -> None:
    assert named_version.lacks(LIST, NAMED_320D)
    assert not named_version.lacks(LIST, Wanted(fuel="diesel", family="318d", power_kw=110))
    assert named_version.named_engine(Wanted(fuel="diesel")) is None  # no family, no power: nothing named
    assert named_version.named_query(LIST, NAMED_320D, 2024) == "BMW 3 Series 320d 190 CV 2024"


async def test_a_named_version_found_on_its_own_page_joins_the_list() -> None:
    acq = _Acq([_entry("320d 190 CV", "BMW 320d Berlina Aut. 190 CV", 190),
                _entry("318d 150 CV", "318d 150 CV", 150)], "BMW 320d Berlina Aut. 190 CV diésel 2.0")  # fmt: skip
    ports = _ports(acq)
    g = await named_version.find_named(ports, LIST, NAMED_320D, 2024)
    assert [v.engine for v in g.versions][-1] == "320d 190 CV" and len(g.versions) == 4
    assert {s["url"] for s in g.sources} == {DEALER, KM77}
    assert ports.versions.put_rows == [g]  # cached for the next chat
    assert acq.calls[0]["limits"]["versions_one_version"] is True
    assert "BMW 3 Series 320d 190 CV 2024 ficha técnica" in acq.calls[0]["queries"]


async def test_nothing_found_leaves_the_list_and_the_cache_alone() -> None:
    acq = _Acq([_entry("320d 190 CV", "an excerpt the page does not have 190 CV", 190)], "BMW 320d 190 CV")
    ports = _ports(acq)
    assert await named_version.find_named(ports, LIST, NAMED_320D, None) is LIST
    assert ports.versions.put_rows == []


async def test_a_list_that_has_the_version_makes_no_search() -> None:
    acq = _Acq([], "")
    named = Wanted(fuel="diesel", family="318d", power_kw=110)
    assert await named_version.find_named(_ports(acq), LIST, named, None) is LIST and acq.calls == []


def test_a_one_version_page_is_wanted_only_when_one_version_is_looked_for() -> None:
    assert _rank(KM77, "BMW", one_version=True) > _rank(KM77, "BMW")
    pages = {KM77: ("320d", "BMW 320d 190 CV diésel"), DEALER: ("Serie 3", "318d 150 CV, 320d 190 CV, 330e 292 CV")}
    assert list(_richest(pages, 3)) == [DEALER]  # a range search keeps range pages only
    assert set(_richest(pages, 3, min_powers=1)) == {KM77, DEALER}
