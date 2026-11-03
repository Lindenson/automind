# ruff: noqa: E501
"""Spec 007 US7 (G36): "посоветуй семейный кроссовер до 25к" gives 2–3 candidates with reasons, not a general text."""

import uuid

from sqlalchemy import delete, select

from automind.domain import intake
from automind.domain.casefile import Budget, CaseCar, CaseFile
from automind.domain.policy import decide
from automind.infrastructure import db
from automind.infrastructure.db.repositories import MessageRepo
from automind.orchestration.graph import build_graph
from automind.orchestration.runner import ChatRunner
from tests.fakes.fake_llm import FakeLLM
from tests.fakes.fixture_search import FixtureSearch

from .conftest import budget_factory, make_ports

LM = intake.LineupModel


def _decide(case):
    return decide(case, "compare", {}, cost_estimate_eur=None, last_fingerprint=None)


def test_no_car_with_a_need_and_a_budget_selects_candidates():
    case = CaseFile(wanted_body="suv", budget=Budget(max_eur=25000))
    assert _decide(case).kind == "SELECT_CANDIDATES"
    family = CaseFile(usage=["FAMILY"], budget=Budget(max_eur=25000))
    assert _decide(family).kind == "SELECT_CANDIDATES"


def test_no_car_and_nothing_else_is_general():
    assert _decide(CaseFile()).kind == "ANSWER_GENERAL"
    assert _decide(CaseFile(wanted_body="suv")).kind == "ANSWER_GENERAL"  # no budget
    named = CaseFile(wanted_body="suv", budget=Budget(max_eur=25000), cars=[CaseCar(key="car#1", request_text="x")])
    assert _decide(named).kind != "SELECT_CANDIDATES"


def test_body_words():
    assert intake.body_of("посоветуй семейный кроссовер до 25к") == "suv"
    assert intake.body_of("un familiar diésel") == "estate"
    assert intake.body_of("что-нибудь до 20 тысяч") is None


POOL = [
    ("Dacia", LM("Duster", "suv", ("petrol", "lpg"), 19990)),
    ("Dacia", LM("Bigster", "suv", ("hybrid",), 24990)),
    ("Toyota", LM("C-HR", "suv", ("hybrid",), 24900)),
    ("Toyota", LM("Yaris", "hatchback", ("hybrid",), 18990)),
    ("Kia", LM("Sportage", "suv", ("hybrid",), None)),
    ("BMW", LM("X3", "suv", ("diesel",), 54000)),
]


def test_candidates_fit_the_body_and_the_budget_one_per_make_first():
    fit = intake.Fit(family=True, annual_km=15000, budget_eur=25000)
    got = intake.pick_candidates(POOL, fit, "suv")
    names = [f"{mk} {m.model}" for mk, m, _ in got]
    assert 2 <= len(got) <= 3 and "BMW X3" not in names and "Toyota Yaris" not in names
    assert len({mk for mk, _, _ in got[:2]}) == 2  # one per make first
    assert all("family_body" in why for _, _, why in got)


def test_an_unpriced_model_fills_in_only_when_needed():
    fit = intake.Fit(family=True, budget_eur=25000)
    few = [p for p in POOL if p[0] in ("Toyota", "Kia")]
    got = intake.pick_candidates(few, fit, "suv")
    assert [m.model for _, m, _ in got] == ["C-HR", "Sportage"]


async def _seed():
    async with db.sessionmaker()() as s:
        await s.execute(delete(db.BrandLineup).where(db.BrandLineup.make.in_(["Dacia", "Toyota", "Kia"])))
        for make, models in (("Dacia", [{"model": "Duster", "body": "suv", "powertrains": ["petrol"],
                                         "price_from_eur": 19990}]),
                             ("Toyota", [{"model": "C-HR", "body": "suv", "powertrains": ["hybrid"],
                                          "price_from_eur": 24900}]),
                             ("Kia", [{"model": "Sportage", "body": "suv", "powertrains": ["hybrid"]}])):  # fmt: skip
            s.add(db.BrandLineup(make=make, market="ES", models=models, sources=[]))
        for make, model, gen, year, name, pt, price in (
            ("Dacia", "Duster", "Mk3", 2024, "1.0 TCe 100 CV ECO-G", "ICE", 19990),
            ("Toyota", "C-HR", "2nd gen", 2024, "1.8 Hybrid 140 CV", "HEV", 24900),
            ("Kia", "Sportage", "NQ5", 2022, "1.6 T-GDi HEV 215 CV", "HEV", None),
        ):
            key = f"{make}|{model}|{gen}|{name}".lower()
            old = (await s.execute(select(db.Variant).where(db.Variant.canonical_key == key))).scalar_one_or_none()
            if old is not None:  # research of an earlier run would make the data fresh: start from the catalog only
                await s.execute(delete(db.ResearchRun).where(db.ResearchRun.variant_id == old.id))
                continue
            s.add(db.Variant(canonical_key=key, make=make, model=model,
                             generation=gen, variant_name=name, powertrain=pt, body_class="SUV", market="ES",
                             model_year_from=year, generation_years_from=year, price_eur=price))  # fmt: skip
        await s.commit()


async def test_advice_without_cars_gives_a_card_with_candidates(saver):
    await _seed()
    llm = FakeLLM()
    llm.responders["asker"] = lambda s, u: "Понял: семейный кроссовер до 25 000 €."
    llm.queue("interpreter", {"request": "compare", "language": "ru",
                              "delta": {"set_budget": {"max_eur": 25000, "intent": "NEW"}, "set_usage": ["FAMILY"]}})  # fmt: skip
    ports = make_ports(llm=llm, search=FixtureSearch("empty"))
    rn = ChatRunner(build_graph(saver, tools=[]), ports, budget_factory(), messages=MessageRepo())
    chat = str(uuid.uuid4())
    r = await rn.run_turn(chat, "посоветуй семейный кроссовер до 25к")
    assert "general" not in llm.roles_called()
    _, data, _ = await rn.ports.cases.latest(chat)
    cars = [f"{c['make']} {c['model']}" for c in data["cars"]]
    assert 2 <= len(cars) <= 3 and "Dacia Duster" in cars and "Toyota C-HR" in cars
    assert data["wanted_body"] == "suv" and all(c["condition"] == "NEW" for c in data["cars"])
    text = (r.confirm or {}).get("text") or r.reply_text or ""
    assert r.action == "CONFIRM_INTAKE", (r.action, text[:300])  # the usual card, the candidates with reasons
    assert "Toyota C-HR" in text and "семейный кузов" in text and "от 24 900 €" in text
    if "Kia Sportage" in cars:
        assert "цену нужно уточнить" in text
