# ruff: noqa: E501
"""009 FR-022 (chat 20b5b7f9): the first message "найди мне подходящую kia для замены моего ленд круер прадо 150
возрастом 15 лет" got "could not map that to the cars we are discussing" (the interpreter returned replace_cars of
car#1 in an empty case) or "which Kia model?" (a Kia without a model). It must lead to 2–3 Kia candidates and
recognise the Prado J150, 15 years old, as the car they replace.

The interpreter's three readings are replayed: the one the v4 prompt asks for, and the two seen live."""

import uuid
from pathlib import Path

import pytest
from sqlalchemy import delete, select

from automind.chat.application.services.identification.candidates import ask_the_model
from automind.chat.dialog.graph import build_graph
from automind.chat.dialog.runner import ChatRunner
from automind.chat.domain.case.casefile import CaseCar, CaseFile
from automind.chat.domain.policy import wants_candidates
from automind.chat.infrastructure.persistence.repositories import MessageRepo
from automind.shared.infrastructure import db
from tests.fakes.fake_llm import FakeLLM
from tests.fakes.fixture_search import FixtureSearch
from tests.golden.runner import load, seed

from .conftest import budget_factory, make_ports

TEXT = "найди мне подходящую kia для замены моего ленд круер прадо 150 возрастом 15 лет"
PRADO = {"request_text": "ленд круер прадо 150 возрастом 15 лет", "make": "Toyota", "model": "Land Cruiser Prado",
         "condition": "USED", "age_years": 15, "constraints": {"generation_hint": "150"}}  # fmt: skip
READINGS = {
    # the v4 prompt: a make to choose from and the user's own car
    "prompt_v4": {"choose_from_make": "Kia", "add_cars": [{**PRADO, "replaced": True}]},
    # live: "для замены" read as a correction of a car that does not exist → "could not map"
    "replace_unknown_key": {"replace_cars": [{"target_key": "car#1", **PRADO}]},
    # live: a Kia without a model next to the Prado → "which model?"
    "bare_make": {"add_cars": [{"request_text": "подходящую kia", "make": "Kia"}, PRADO]},
}
KIA = [{"model": "Sportage", "body": "suv", "powertrains": ["hybrid", "phev"], "price_from_eur": 33000},
       {"model": "Sorento", "body": "suv", "powertrains": ["hybrid", "phev", "diesel"], "price_from_eur": 47000},
       {"model": "Picanto", "body": "hatchback", "powertrains": ["petrol"], "price_from_eur": 14000}]  # fmt: skip


async def _seed() -> None:
    await seed(load(Path(__file__).resolve().parents[1] / "golden" / "g1_bigster_prado.yaml"))  # the Prado J150
    async with db.sessionmaker()() as s:
        await s.execute(delete(db.BrandLineup).where(db.BrandLineup.make == "Kia"))
        s.add(db.BrandLineup(make="Kia", market="ES", models=KIA, sources=[]))
        for model, gen, name, pt, price in (("Sportage", "NQ5", "1.6 T-GDi HEV 215 CV", "HEV", 33000),
                                            ("Sorento", "MQ4", "1.6 T-GDi HEV 215 CV", "HEV", 47000),
                                            ("Picanto", "JA", "1.0 DPI 63 CV", "ICE", 14000)):  # fmt: skip
            key = f"kia|{model}|{gen}|{name}".lower()
            old = (await s.execute(select(db.Variant).where(db.Variant.canonical_key == key))).scalar_one_or_none()
            if old is not None:
                await s.execute(delete(db.ResearchRun).where(db.ResearchRun.variant_id == old.id))
                continue
            s.add(db.Variant(canonical_key=key, make="Kia", model=model, generation=gen, variant_name=name,
                             powertrain=pt, body_class="HATCHBACK" if model == "Picanto" else "SUV", market="ES",
                             model_year_from=2022, generation_years_from=2022, price_eur=price))  # fmt: skip
        await s.commit()


@pytest.mark.parametrize("reading", sorted(READINGS))
async def test_a_kia_to_replace_my_prado_proposes_kia_candidates(saver, reading):
    await _seed()
    llm = FakeLLM()
    llm.responders["asker"] = lambda s, u: "Понял: подберу Kia на замену вашему Prado."
    llm.queue("interpreter", {"request": "compare", "language": "ru", "delta": READINGS[reading]})
    rn = ChatRunner(build_graph(saver, tools=[]), make_ports(llm=llm, search=FixtureSearch("empty")),
                    budget_factory(), messages=MessageRepo())  # fmt: skip
    chat = str(uuid.uuid4())
    r = await rn.run_turn(chat, TEXT)
    text = (r.confirm or {}).get("text") or r.reply_text or ""
    assert "could not map" not in text and "Не понял, к какой из машин" not in text
    assert "general" not in llm.roles_called() and "resolver" not in llm.roles_called()
    _, data, _ = await rn.ports.cases.latest(chat)
    assert data is not None, text  # "could not map": the interpreter output was refused, no case
    kias = [c for c in data["cars"] if c["make"] == "Kia"]
    assert 2 <= len(kias) <= 3 and all(c["model"] for c in kias), data["cars"]  # never a Kia without a model
    assert {c["model"] for c in kias} <= {"Sportage", "Sorento"}  # SUVs like the Prado they replace
    prado = [c for c in data["cars"] if c["model"] == "Land Cruiser Prado"]
    assert len(prado) == 1 and prado[0]["replaced"] and prado[0]["condition"] == "USED"
    assert prado[0]["age_years"] == 15 and prado[0]["year"] == 2011
    assert all(c["condition"] == "NEW" for c in kias)  # the Prado's "used" is not passed on to the candidates
    pending = data.get("pending") or {}
    assert not any(it.get("kind") == "MODEL" for it in pending.get("items", [])), pending  # never "which model?"
    assert data.get("wanted_make") == "Kia"
    assert r.action == "CONFIRM_INTAKE", (r.action, text[:400])
    assert "кандидатов Kia на замену вашему Toyota Land Cruiser Prado J150" in text and "(~2011)" in text


def test_a_make_to_choose_from_selects_candidates_until_one_of_its_cars_is_in_the_case():
    own = CaseCar(key="car#1", request_text="прадо", make="Toyota", model="Land Cruiser Prado", replaced=True)
    case = CaseFile(wanted_make="Kia", cars=[own], next_car_no=2)
    assert wants_candidates(case)  # no budget needed: the make is the need
    case.candidates = [{"key": "car#2", "make": "Kia", "model": "Sportage"}]
    assert not wants_candidates(case)  # proposed once
    case.candidates = []
    assert ask_the_model(case) is not None  # nothing to propose: "which Kia model?" with the line-up
    assert case.cars[-1].make == "Kia" and case.cars[-1].model is None and not wants_candidates(case)
    assert ask_the_model(case) is None
