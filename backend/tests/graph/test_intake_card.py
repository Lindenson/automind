# ruff: noqa: E501
"""Spec 005 US5 (FR-019–FR-021): one card before research — every item has a basis; a chip edit is applied by code
(no model call) and highlighted; one "yes" confirms the cars and approves the cost; research is only for the cars on
the card."""

import uuid

from sqlalchemy import select

from automind.infrastructure import db
from automind.infrastructure.db.repositories import MessageRepo
from automind.orchestration.graph import build_graph
from automind.orchestration.runner import ChatRunner
from tests.fakes.fake_llm import FakeLLM, FixedEstimator
from tests.fakes.fixture_search import FixtureSearch

from .conftest import budget_factory, make_ports
from .test_corrections import _seed_ateca


def _runner(saver, llm):
    ports = make_ports(llm=llm, search=FixtureSearch("empty"))
    ports.estimator = FixedEstimator(eur_per_job=0.2)
    return ChatRunner(build_graph(saver, tools=[]), ports, budget_factory(), messages=MessageRepo())


def _item(card: dict, key: str, field: str) -> dict:
    car = next(c for c in card["cars"] if c["key"] == key)
    return next(i for i in car["items"] if i["field"] == field)


async def test_card_basis_edit_and_one_yes(saver):
    await _seed_ateca()
    llm = FakeLLM()
    llm.responders["asker"] = lambda s, u: "Понял."
    llm.queue("reporter", "Отчёт.", "Отчёт.")
    llm.responders["extractor"] = lambda s, u: {"claims": [], "is_about_variant": True}
    add = {"request_text": "SEAT Ateca 1.0", "make": "SEAT", "model": "Ateca", "condition": "NEW"}
    llm.queue("interpreter", {"request": "compare", "language": "ru", "delta": {"add_cars": [add]}})
    rn = _runner(saver, llm)
    chat = str(uuid.uuid4())
    w = await rn.run_turn(chat, "SEAT Ateca 1.0 новый")
    assert w.status == "WAITING_CONFIRMATION" and w.confirm["kind"] == "intake", (w.status, w.reply_text)
    card = w.confirm["card"]
    for car in card["cars"]:
        for it in car["items"]:
            assert it["basis"] in ("STATED", "INFERRED", "LOOKED_UP", "ASSUMED"), it
            if it["basis"] == "LOOKED_UP":
                assert it.get("source"), it
    assert _item(card, "car#1", "engine")["basis"] == "STATED" and "1.0" in _item(card, "car#1", "engine")["value"]
    assert _item(card, "car#1", "condition")["basis"] == "STATED"
    assert any(p["field"] == "annual_km" and p["basis"] == "ASSUMED" for p in card["profile"])
    assert "Проверьте" in w.confirm["text"] and w.confirm["options"][0]["label"] == "Да, исследовать"

    # a chip edit: applied by code, the car re-identified, the change highlighted — no model call
    calls = len(llm.roles_called())
    w2 = await rn.resume(
        chat, {"choice": "edit_field", "car_key": "car#1", "field": "engine", "value": "1.5 TSI 150 CV"}
    )
    assert w2.confirm is not None and w2.confirm["kind"] == "intake", (w2.status, w2.reply_text)
    engine = _item(w2.confirm["card"], "car#1", "engine")
    assert "1.5" in engine["value"] and engine.get("changed") and "1.0" in (engine.get("before") or "")
    assert len(llm.roles_called()) == calls

    # one "yes": the car confirmed, research runs for the 1.5 only
    done = await rn.resume(chat, {"choice": "yes"})
    _, data, _ = await rn.ports.cases.latest(chat)
    assert data["cars"][0]["resolution"] == "CONFIRMED" and data["intake"]["card_confirmed"]
    jobs = await make_ports().jobs.for_turn(done.turn_id)
    assert jobs, (done.status, done.action)
    async with db.sessionmaker()() as s:
        ids = {j.variant_id for j in jobs}
        cc = {v.engine_cc for v in (await s.execute(select(db.Variant).where(db.Variant.id.in_(ids)))).scalars()}
    assert cc == {1498}


async def test_free_text_on_the_card_is_a_correction(saver):
    await _seed_ateca()
    llm = FakeLLM()
    llm.responders["asker"] = lambda s, u: "Понял."
    add = {"request_text": "SEAT Ateca 1.0", "make": "SEAT", "model": "Ateca", "condition": "NEW"}
    llm.queue("interpreter", {"request": "compare", "language": "ru", "delta": {"add_cars": [add]}})
    rn = _runner(saver, llm)
    chat = str(uuid.uuid4())
    await rn.run_turn(chat, "SEAT Ateca 1.0 новый")
    fix = {"target_key": "car#1", "constraints": {"engine_hint": {"displacement_l": 1.5, "evidence": "1.5"}}}
    llm.queue("interpreter", {"request": "correction", "language": "ru", "delta": {"set_car_context": [fix]}})
    w = await rn.resume(chat, {"choice": "text", "text": "нет, 1.5"})
    assert w.confirm is not None and w.confirm["kind"] == "intake"
    assert "1.5" in _item(w.confirm["card"], "car#1", "engine")["value"]
