# ruff: noqa: E501
"""Spec 005 US3 (FR-012–FR-015): a correction of the engine re-identifies the car even when it was resolved, the
old version is never researched, the change is kept for "before → after"; an engine that does not exist is answered
with the engines that do (chat 5be54966: "Ateca 1.5, you wrote 1.0" was ignored). Stands in for golden G23."""

import uuid

from automind.application.interpret import Interpretation, engine_hints
from automind.infrastructure import db
from automind.infrastructure.db.repositories import MessageRepo
from automind.orchestration.graph import build_graph
from automind.orchestration.runner import ChatRunner
from tests.fakes.fake_llm import FakeLLM, FixedEstimator
from tests.fakes.fixture_search import FixtureSearch

from .conftest import budget_factory, forget_make, make_ports


async def _seed_ateca() -> None:
    await forget_make("SEAT")
    async with db.sessionmaker()() as s:
        for name, cc, kw in (("1.0 TSI 110 CV Style", 999, 81), ("1.5 TSI 150 CV DSG FR", 1498, 110)):
            s.add(db.Variant(canonical_key=f"seat|ateca|kh7|{name.lower()}|{uuid.uuid4().hex[:6]}", make="SEAT",
                             model="Ateca", generation="KH7", variant_name=name, powertrain="ICE", body_class="SUV",
                             generation_years_from=2016, generation_years_to=None, vehicle_class="compact",
                             engine_cc=cc, power_kw=kw, fuel="petrol"))  # fmt: skip
        await s.commit()


def _runner(saver, llm):
    ports = make_ports(llm=llm, search=FixtureSearch("empty"))
    ports.estimator = FixedEstimator(eur_per_job=0.2)  # research waits for a cost confirmation: nothing runs
    return ChatRunner(build_graph(saver, tools=[]), ports, budget_factory(), messages=MessageRepo())


def test_engine_in_trim_hint_moves_to_engine_hint() -> None:
    i = Interpretation.model_validate({"request": "correction", "language": "ru", "delta": {"set_car_context": [
        {"target_key": "car#2", "constraints": {"trim_hint": "1.5"}}]}})  # fmt: skip
    out = engine_hints(i, "давай seat хотя бы с двигателем 1.5")
    k = out.delta.set_car_context[0].constraints
    assert k is not None and k.trim_hint is None and k.engine_hint is not None and k.engine_hint.displacement_l == 1.5
    j = Interpretation.model_validate({"request": "compare", "language": "en", "delta": {"add_cars": [
        {"request_text": "Ateca FR 1.5 TSI", "make": "SEAT", "model": "Ateca", "constraints": {"trim_hint": "FR 1.5 TSI"}}]}})  # fmt: skip
    k2 = engine_hints(j, "Ateca FR 1.5 TSI").delta.add_cars[0].constraints
    assert (
        k2.trim_hint == "FR 1.5 TSI" and k2.engine_hint is not None and k2.engine_hint.family == "TSI"
    )  # a trim stays


async def test_engine_correction_reidentifies_a_resolved_car(saver):
    await _seed_ateca()
    llm = FakeLLM()
    llm.responders["asker"] = lambda s, u: "Понял."
    add = {"request_text": "SEAT Ateca 1.0", "make": "SEAT", "model": "Ateca", "condition": "NEW"}
    llm.queue("interpreter", {"request": "compare", "language": "ru", "delta": {"add_cars": [add]}})
    rn = _runner(saver, llm)
    chat = str(uuid.uuid4())
    w = await rn.run_turn(chat, "SEAT Ateca 1.0 новый")
    _, data, _ = await rn.ports.cases.latest(chat)
    assert "1.0 TSI" in (data["cars"][0]["label"] or ""), (w.status, w.reply_text, data["cars"][0])
    fix = {"target_key": "car#1", "constraints": {"engine_hint": {"displacement_l": 1.5, "evidence": "1.5"}}}
    llm.queue("interpreter", {"request": "correction", "language": "ru", "delta": {"set_car_context": [fix]}})
    if w.status == "WAITING_CONFIRMATION":
        await rn.resume(chat, {"choice": "text", "text": "1.5, а не 1.0"})
    else:
        await rn.run_turn(chat, "1.5, а не 1.0")
    _, data, _ = await rn.ports.cases.latest(chat)
    car = data["cars"][0]
    assert "1.5 TSI" in (car["label"] or ""), car
    assert "1.0 TSI" in (car["previous_label"] or "")
    async with db.sessionmaker()() as s:
        from sqlalchemy import select

        old = (
            await s.execute(select(db.Variant).where(db.Variant.make == "SEAT", db.Variant.engine_cc == 999))
        ).scalar_one()
        jobs = (await s.execute(select(db.ResearchJob).where(db.ResearchJob.variant_id == old.id,
                                                             db.ResearchJob.status == "DONE"))).scalars().all()  # fmt: skip
    assert jobs == []  # the corrected-away version was never researched


async def test_engine_that_does_not_exist_offers_the_existing_ones(saver):
    await _seed_ateca()
    llm = FakeLLM()
    llm.responders["asker"] = lambda s, u: "Понял."
    add = {"request_text": "SEAT Ateca 2.5 diesel", "make": "SEAT", "model": "Ateca", "condition": "NEW",
           "constraints": {"engine_hint": {"displacement_l": 2.5, "fuel": "diesel", "evidence": "2.5 diesel"}}}  # fmt: skip
    llm.queue("interpreter", {"request": "compare", "language": "ru", "delta": {"add_cars": [add]}})
    llm.queue("resolver", {"make": "SEAT", "model": "Ateca", "generation": "KH7", "generation_years_from": 2016,
                           "generation_years_to": None, "variant_name": "1.5 TSI 150 CV", "powertrain": "ICE",
                           "engine_cc": 1498, "power_kw": 110, "fuel": "petrol", "certainty": "ambiguous",
                           "alternatives": ["2.0 TDI 150 CV"], "note": "No 2.5 diesel is sold"})  # fmt: skip
    rn = _runner(saver, llm)
    r = await rn.run_turn(str(uuid.uuid4()), "SEAT Ateca 2.5 дизель")
    assert r.action == "ASK", (r.status, r.reply_text)
    assert "двигатель" in r.reply_text.lower() and "1.5 TSI" in r.reply_text, r.reply_text
