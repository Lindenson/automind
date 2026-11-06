"""Owner decision 2026-11-05: a petrol/diesel car whose versions list the web sources do not give gets its ladder
from the EU registrations (one version per engine size and registered kW, the kW being a combustion car's power):
a used 2016 Toyota Land Cruiser J150 diesel is identified as the 2.8 D-4D 130 kW without an empty power question,
and the card says the list came from the registrations."""

from __future__ import annotations

import uuid

from sqlalchemy import delete

from automind.acquisition.gold import versions as gv
from automind.acquisition.gold.domain.match import DatasetRow
from automind.chat.application.services.identification import resolve
from automind.chat.dialog.graph import build_graph
from automind.chat.dialog.runner import ChatRunner
from automind.chat.infrastructure.persistence.repositories import MessageRepo
from automind.shared.infrastructure import db
from automind.shared.infrastructure.config.loader import reference
from tests.fakes.fake_llm import FakeLLM
from tests.fakes.fixture_search import FixtureSearch

from .conftest import budget_factory, engine, forget_make, make_ports
from .test_version_question import EmptyStore


def _eea(fuel: str, kw: float, cc: int, year: int, regs: int, name: str = "LAND CRUISER") -> DatasetRow:
    return DatasetRow(dataset="eea_co2", make="TOYOTA", model=name, fuel=fuel, power_kw=kw, displacement_cc=cc,
                      mass_running_order_kg=None, year_from=year, year_to=year, registrations=regs, values={},
                      units={}, record_key=f"TOYOTA|{name}|{fuel}|{kw}|{cc}|{year}")  # fmt: skip


async def toyota_rows(make: str) -> list[DatasetRow]:
    """The J150's diesels: the 3.0 D-4D 127 kW until 2015, the 2.8 D-4D 130 kW from 2015 (and 150 kW from 2020); a
    petrol V6; a handful of grey imports below the registrations floor; another model."""
    return [
        _eea("diesel", 127, 2982, 2013, 4100), _eea("diesel", 127, 2982, 2014, 3900),
        _eea("diesel", 127, 2982, 2015, 900), _eea("diesel", 130, 2755, 2015, 2600),
        _eea("diesel", 130, 2755, 2016, 5200), _eea("diesel", 130, 2755, 2017, 5400),
        _eea("diesel", 150, 2755, 2020, 4800), _eea("petrol", 207, 3956, 2016, 300),
        _eea("diesel", 120, 2494, 2016, 3), _eea("diesel", 130, 2755, 2016, 900, "HILUX"),
    ]  # fmt: skip


async def _catalog() -> None:
    await forget_make("Toyota")
    ident = resolve.VariantIdentity(make="Toyota", model="Land Cruiser", generation="J150", variant_name="2.8 D-4D",
                                    powertrain="ICE", body_class="SUV", generation_years_from=2009,
                                    generation_years_to=2023, engine_cc=2755, fuel="diesel",
                                    certainty="exact")  # fmt: skip
    await resolve.upsert_variant(ident, reference({}))
    async with db.sessionmaker()() as s:
        await s.execute(delete(db.SearchCache).where(db.SearchCache.key == gv._key("Toyota")))
        await s.commit()


CAR = {"request_text": "Land Cruiser J150 2016 дизель б/у", "make": "Toyota", "model": "Land Cruiser",
       "condition": "USED", "year": 2016,
       "constraints": {"engine_hint": {"fuel": "diesel", "evidence": "дизель"}}}  # fmt: skip


async def test_used_land_cruiser_diesel_ladder_from_registrations(saver) -> None:
    await _catalog()
    llm = FakeLLM()
    llm.responders["asker"] = lambda s, u: "Понял."
    llm.queue("interpreter", {"request": "compare", "language": "ru", "delta": {"add_cars": [CAR]}})
    ports = make_ports(llm=llm, search=FixtureSearch("empty"))
    store = EmptyStore()
    ports.versions = store  # type: ignore[assignment]
    engine(ports).datasets = toyota_rows
    rn = ChatRunner(build_graph(saver, tools=[]), ports, budget_factory(), messages=MessageRepo())
    chat = str(uuid.uuid4())
    r = await rn.run_turn(chat, "б/у Land Cruiser J150 2016, дизель")
    assert "мощность: ?" not in r.reply_text, r.reply_text  # no empty power question
    _, data, _ = await rn.ports.cases.latest(chat)
    car = data["cars"][0]
    assert car["ladder"]["certainty"] == "SOURCED", car
    assert car["ladder"]["source_name"] == "EU registrations (EEA CO2 / RDW)", car
    assert "130 kW" in (car["label"] or "") and "177 CV" in (car["label"] or ""), car
    assert store.put_calls == 0  # a registrations list is not kept as a sourced web list
