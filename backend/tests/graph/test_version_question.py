"""Live chat 6e001ee0: a NEW Kia Sorento PHEV, no list of versions in the web sources, one catalog row (1.6 T-GDi
PHEV 4x4 Drive, 265 CV, MQ4 2020–). The version question came with no real options: the old row without its power,
"choose for me" and "remove" — the user had to type a power. Now the question offers the versions the EU
registration datasets list (the 2024 facelift's engine first, by engine size, engine kW and years — never a power
the data does not give), the catalog row with its power and years, "another one (I'll type it)" and "choose for me";
the facelift's chip is never answered with the old row.
"""

from __future__ import annotations

import uuid

from sqlalchemy import delete

from automind.acquisition.gold.domain.records import DatasetRow
from automind.acquisition.identity_readers.infrastructure.version_store import cache_key
from automind.chat.application.services.identification.catalogue import upsert_variant
from automind.chat.application.services.identification.contracts import VariantIdentity
from automind.chat.dialog.graph import build_graph
from automind.chat.dialog.runner import ChatRunner
from automind.chat.infrastructure.persistence.repositories import MessageRepo
from automind.delivery.bootstrap import reference
from automind.shared.infrastructure import db
from tests.fakes.fake_llm import FakeLLM
from tests.fakes.fixture_search import FixtureSearch

from .conftest import budget_factory, engine, forget_make, make_ports

OLD_ROW = "1.6 T-GDi PHEV 4x4 Drive"


class EmptyStore:
    """The versions cache: nothing cached, a found list would be kept."""

    def __init__(self) -> None:
        self.put_calls = 0

    async def get(self, make, model, generation, year, new, ttl_days):  # noqa: ANN001, ANN201
        return None

    async def put(self, g):  # noqa: ANN001, ANN201
        self.put_calls += 1


def _eea(fuel: str, kw: float, cc: int, year: int, regs: int, name: str = "SORENTO") -> DatasetRow:
    return DatasetRow(dataset="eea_co2", make="KIA", model=name, fuel=fuel, power_kw=kw, displacement_cc=cc,
                      mass_running_order_kg=None, year_from=year, year_to=year, registrations=regs, values={},
                      units={}, record_key=f"KIA|{name}|{fuel}|{kw}|{cc}|{year}")  # fmt: skip


async def kia_rows(make: str) -> list[DatasetRow]:
    """What the EEA CO2 tables give for KIA (pinned from the live data, 2026-11-05): the Sorento PHEV's 132 kW engine
    2021–2023 and the facelift's 118 kW engine from 2024; HEV and diesel versions; another model."""
    return [
        _eea("phev", 132, 1598, 2021, 2400, "SORENTO/PHEV/5S/GOLD/UVO/1.6 T"), _eea("phev", 132, 1598, 2022, 3100),
        _eea("phev", 132, 1598, 2023, 2900), _eea("phev", 118, 1598, 2024, 3300),
        _eea("hybrid", 132, 1598, 2024, 5200), _eea("diesel", 142, 2151, 2024, 1800),
        _eea("phev", 132, 1598, 2024, 1200, "SPORTAGE"),
    ]  # fmt: skip


async def _catalog_row() -> None:
    await forget_make("Kia")  # earlier tests' Kia rows (the 2024 288 CV row would make this another case)
    ident = VariantIdentity(make="Kia", model="Sorento", generation="MQ4", variant_name=OLD_ROW,
                                    powertrain="PHEV", body_class="SUV", generation_years_from=2020,
                                    generation_years_to=None, engine_cc=1598, power_kw=195, fuel="phev",
                                    certainty="exact")  # fmt: skip
    await upsert_variant(ident, reference({}))
    async with db.sessionmaker()() as s:  # the dataset rows are read live (faked) and cached for this test only
        await s.execute(delete(db.SearchCache).where(db.SearchCache.key == cache_key("Kia")))
        await s.commit()


def _ru(delta: dict) -> dict:
    return {"request": "compare", "language": "ru", "delta": delta}


CAR = {"request_text": "новый Sorento PHEV", "make": "Kia", "model": "Sorento", "condition": "NEW",
       "constraints": {"engine_hint": {"fuel": "phev", "evidence": "PHEV"}}}  # fmt: skip


def _runner(saver, llm: FakeLLM) -> tuple[ChatRunner, FixtureSearch, EmptyStore]:  # noqa: ANN001
    search = FixtureSearch("empty")  # live: "the versions list was not found in sources", even the harder searches
    ports = make_ports(llm=llm, search=search)
    store = EmptyStore()
    ports.versions = store  # type: ignore[assignment]
    engine(ports).datasets = kia_rows
    return ChatRunner(build_graph(saver, tools=[]), ports, budget_factory(), messages=MessageRepo()), search, store


def _chips(r) -> list[str]:  # noqa: ANN001
    return [x["label"] for b in r.blocks if b.get("type") == "quick_replies" for x in b["items"]]


async def test_new_sorento_phev_version_question_offers_registered_versions_and_choose_for_me(saver) -> None:
    await _catalog_row()
    llm = FakeLLM()
    llm.responders["asker"] = lambda s, u: "Понял: новый Kia Sorento PHEV."
    llm.queue("interpreter", _ru({"add_cars": [CAR]}))
    rn, search, store = _runner(saver, llm)
    r = await rn.run_turn(str(uuid.uuid4()), "хочу новый Sorento PHEV")
    assert r.action == "ASK", r.reply_text
    assert "Kia Sorento · плагин-гибрид PHEV · мощность: ?" in r.reply_text, r.reply_text  # as live
    chips = _chips(r)
    facelift = "1.6 PHEV · двигатель 118 kW · 2024–"
    assert chips[:2] == [facelift, f"{OLD_ROW} 265 CV · 2020–2023"], chips
    assert "Другая (напишу)" in chips and "Выбери сам" in chips, chips
    assert not any("CV" in c and "118" in c for c in chips)  # the engine kW is never shown as the car's power
    assert facelift in r.reply_text  # the question names the options
    notices = [b["text"] for b in r.blocks if b.get("type") == "notice"]
    assert any("2024" in n and "ЕС" in n for n in notices), notices
    typing = [x for b in r.blocks if b.get("type") == "quick_replies" for x in b["items"] if x.get("typing")]
    assert [x["label"] for x in typing] == ["Другая (напишу)"]
    # the datasets were read before the web search: the searches ask for the facelift's year
    assert any("2024" in q for q in search.queries[:2]), search.queries
    assert store.put_calls == 0


async def test_the_facelift_chip_is_never_answered_with_the_old_row(saver) -> None:
    await _catalog_row()
    llm = FakeLLM()
    llm.responders["asker"] = lambda s, u: "Понял."
    llm.queue("interpreter", _ru({"add_cars": [CAR]}))
    seen: list[str] = []

    def resolver(system: str, user: str) -> dict:
        seen.append(user)
        return {"make": "Kia", "model": "Sorento", "generation": "MQ4", "generation_years_from": 2020,
                "generation_years_to": None, "variant_name": "1.6 T-GDi PHEV 288 CV 4x4", "powertrain": "PHEV",
                "body_class": "SUV", "engine_cc": 1598, "power_kw": 212, "fuel": "phev",
                "certainty": "exact"}  # fmt: skip

    llm.responders["resolver"] = resolver
    rn, _, _ = _runner(saver, llm)
    chat = str(uuid.uuid4())
    r1 = await rn.run_turn(chat, "хочу новый Sorento PHEV")
    facelift = next(c for c in _chips(r1) if "2024–" in c)
    await rn.run_turn(chat, facelift)
    _, data, _ = await rn.ports.cases.latest(chat)
    car = data["cars"][0]
    assert seen and "2024" in seen[0], seen  # the resolver is told which version the user picked
    assert "288" in (car["label"] or "") and "265" not in (car["label"] or ""), car
