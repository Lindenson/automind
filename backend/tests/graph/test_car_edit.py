"""Spec 010 US10 (T090, T091; FR-035–FR-037): "Change" on a car is applied by code — no interpreter call —, the case
file changes, the edit is an intake event and tells the previous answer it had the wrong car; after a confirmation an
"Agreed" message with the version line stays in the chat."""

import uuid

from sqlalchemy import select

from automind.chat.application.services.report.blocks import car_view
from automind.chat.dialog.graph import build_graph
from automind.chat.dialog.runner import ChatRunner
from automind.chat.domain.case import CaseCar, CaseFile
from automind.chat.infrastructure.persistence.repositories import MessageRepo
from automind.observability.infrastructure.outcomes import OutcomeRepo
from automind.shared.infrastructure import db
from automind.shared.infrastructure.db.models import TurnOutcome
from tests.fakes.fake_llm import FakeLLM, FixedEstimator
from tests.fakes.fixture_search import FixtureSearch

from .conftest import budget_factory, make_ports
from .test_corrections import _seed_ateca


def _runner(saver, llm):
    ports = make_ports(llm=llm, search=FixtureSearch("empty"))
    ports.estimator = FixedEstimator(eur_per_job=0.2)
    ports.outcomes = OutcomeRepo(ports.ref.outcome, "test")
    return ChatRunner(build_graph(saver, tools=[]), ports, budget_factory(), messages=MessageRepo())


def _llm() -> FakeLLM:
    llm = FakeLLM()
    llm.responders["asker"] = lambda s, u: "Понял."
    llm.responders["reporter"] = lambda s, u: "Отчёт."
    llm.responders["extractor"] = lambda s, u: {"claims": [], "is_about_variant": True}
    return llm


async def _until_done(rn: ChatRunner, chat: str, r):
    for _ in range(3):
        if r.status != "WAITING_CONFIRMATION":
            return r
        r = await rn.resume(chat, {"choice": "yes"})
    return r


async def test_change_engine_is_applied_by_code_and_marks_the_previous_turn(saver):
    await _seed_ateca()
    llm = _llm()
    add = {"request_text": "SEAT Ateca 1.0", "make": "SEAT", "model": "Ateca", "condition": "NEW"}
    llm.queue("interpreter", {"request": "compare", "language": "ru", "delta": {"add_cars": [add]}})
    rn = _runner(saver, llm)
    chat = str(uuid.uuid4())
    async with db.sessionmaker()() as s:  # intake events are kept for chats that exist
        s.add(db.Chat(id=chat))
        await s.commit()
    first = await _until_done(rn, chat, await rn.run_turn(chat, "SEAT Ateca 1.0 новый"))
    assert first.status == "DONE", (first.status, first.reply_text)
    _, data, _ = await rn.ports.cases.latest(chat)
    assert "1.0 TSI" in (data["cars"][0]["label"] or "")

    # the "Agreed" entry is a stored message with the version line (FR-035)
    msgs = await MessageRepo().history(chat)
    agreed = [m for m in msgs if any(b.get("type") == "agreed" for b in m.blocks or [])]
    assert len(agreed) == 1 and agreed[0].role == "assistant", [(m.role, m.text) for m in msgs]
    car = agreed[0].blocks[0]["cars"][0]
    assert car["key"] == "car#1" and "1.0" in (car["variant_label"] or "") and car["basis"] in ("STATED", "LOOKED_UP")

    # "Change" → engine 1.5: no interpreter call, the case changes, the car is identified again
    interp_calls = llm.roles_called().count("interpreter")
    preset = {"kind": "car_edit", "car_key": "car#1", "field": "engine", "value": "1.5 TSI 150 CV", "language": "ru"}
    r = await rn.run_turn(chat, "✎ car#1: engine → 1.5 TSI 150 CV", preset=preset)
    r = await _until_done(rn, chat, r)
    assert llm.roles_called().count("interpreter") == interp_calls
    _, data, _ = await rn.ports.cases.latest(chat)
    assert "1.5 TSI" in (data["cars"][0]["label"] or ""), data["cars"][0]
    assert "1.0 TSI" in (data["cars"][0]["previous_label"] or "")

    async with db.sessionmaker()() as s:
        kinds = [(e.kind, e.car_key, e.item) for e in (await s.execute(
            select(db.IntakeEvent).where(db.IntakeEvent.chat_id == chat))).scalars()]  # fmt: skip
        outs = list((await s.execute(select(TurnOutcome).where(TurnOutcome.chat_id == chat)
                                     .order_by(TurnOutcome.created_at))).scalars())  # fmt: skip
    assert ("CARD_EDITED", "car#1", "engine") in kinds
    first_out = next(o for o in outs if o.turn_id == first.turn_id)
    assert (first_out.signals or {}).get("wrong_car") and "wrong_car" in first_out.failure_classes

    # the edit is stored with the hidden role `edit`: never shown, never read by the interpreter
    roles = [m.role for m in await MessageRepo().history(chat)]
    assert "edit" in roles


async def test_remove_and_not_this_car_build_the_delta_by_code(saver):
    case = CaseFile(cars=[CaseCar(key="car#1", request_text="SEAT Ateca", make="SEAT", model="Ateca"),
                          CaseCar(key="car#2", request_text="VW Golf", make="Volkswagen", model="Golf")])  # fmt: skip
    assert car_view.edit_delta(case, "car#2", "remove", "").remove_cars == ["car#2"]
    d = car_view.edit_delta(case, "car#1", "not_this_car", "SEAT Arona")
    assert d.replace_cars[0].make == "SEAT" and d.replace_cars[0].model == "Arona"
    g = car_view.edit_delta(case, "car#1", "gearbox", "DSG")
    assert g.replace_cars[0].constraints is not None and g.replace_cars[0].constraints.gearbox_hint == "dct"
    for bad in (("car#9", "trim", "FR"), ("car#1", "colour", "red"), ("car#1", "engine", "")):
        try:
            car_view.edit_delta(case, *bad)
        except (ValueError, KeyError):
            continue
        raise AssertionError(bad)


async def test_case_payload_carries_the_version_line_and_the_choices(saver):
    await _seed_ateca()
    async with db.sessionmaker()() as s:
        v = await s.execute(select(db.Variant).where(db.Variant.make == "SEAT", db.Variant.engine_cc == 999))
        row = v.scalar_one()
    car1 = CaseCar(key="car#1", request_text="SEAT Ateca", make="SEAT", model="Ateca", condition="NEW",
                   variant_id=row.id, label=row.label, resolution="CONFIRMED")  # fmt: skip
    case = CaseFile(cars=[car1])
    payload = await car_view.case_payload(case)
    car = payload["cars"][0]
    assert car["variant_label"].startswith("1.0 TSI 110 CV"), car["variant_label"]
    assert any("1.5" in o for o in car["options"]["engine"]), car["options"]
    assert not any(o.startswith("1.0") for o in car["options"]["engine"])


async def test_change_while_the_card_is_open_replaces_the_question(saver):
    await _seed_ateca()
    llm = _llm()
    add = {"request_text": "SEAT Ateca 1.0", "make": "SEAT", "model": "Ateca", "condition": "NEW"}
    llm.queue("interpreter", {"request": "compare", "language": "en", "delta": {"add_cars": [add]}})
    rn = _runner(saver, llm)
    chat = str(uuid.uuid4())
    w = await rn.run_turn(chat, "SEAT Ateca 1.0 new")
    assert w.status == "WAITING_CONFIRMATION", (w.status, w.reply_text)
    preset = {"kind": "car_edit", "car_key": "car#1", "field": "engine", "value": "1.5 TSI 150 CV"}
    r = await rn.run_turn(chat, "✎ car#1: engine → 1.5 TSI 150 CV", preset=preset)
    assert llm.roles_called().count("interpreter") == 1
    assert (await rn.ports.turns.get(w.turn_id)).status == "CANCELLED"
    r = await _until_done(rn, chat, r)
    _, data, _ = await rn.ports.cases.latest(chat)
    assert "1.5 TSI" in (data["cars"][0]["label"] or ""), (r.status, data["cars"][0])
