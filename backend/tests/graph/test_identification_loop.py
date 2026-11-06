"""US8 in a turn (spec 004 FR-030/FR-031): an answer that does not settle a car is asked again, nothing is
researched until every car is settled, "choose for me" and "remove this car" work."""

import uuid

import pytest

from automind.chat.dialog.graph import build_graph
from automind.chat.dialog.runner import ChatRunner
from automind.chat.infrastructure.persistence.repositories import MessageRepo
from tests.fakes.fake_llm import FakeLLM
from tests.fakes.fixture_search import FixtureSearch

from .conftest import budget_factory, make_ports
from .test_research_flow import MAKE
from .test_research_flow import fresh_variant as fresh_variant  # noqa: F401  (fixture)

pytestmark = pytest.mark.usefixtures("fresh_variant")
NOTHING = {"request": "compare", "language": "en", "delta": {}}


def _runner(saver, llm):
    ports = make_ports(llm=llm, search=FixtureSearch("empty"))
    return ChatRunner(build_graph(saver, tools=[]), ports, budget_factory(), messages=MessageRepo())


async def test_nonsense_answer_to_a_car_question_is_asked_again(saver):
    llm = FakeLLM().queue(
        "interpreter",
        {"request": "compare", "language": "en", "delta": {"add_cars": [{"request_text": "that one"}]}},
        NOTHING,
    )
    llm.queue("asker", "Which exact car do you mean?", "Which exact car do you mean?")
    rn = _runner(saver, llm)
    chat = str(uuid.uuid4())
    r1 = await rn.run_turn(chat, "compare that one")
    assert r1.action == "ASK", r1.reply_text
    r2 = await rn.run_turn(chat, "qwerty asdf")
    assert r2.action == "ASK", (r2.action, r2.reply_text)
    assert "did not understand" in r2.reply_text and "qwerty asdf" in r2.reply_text
    replies = next(b for b in r2.blocks if b["type"] == "quick_replies")["items"]
    assert any("Remove" in i["label"] for i in replies)
    assert r2.usage["search_calls"] == 0 and "resolver" not in llm.roles_called()
    _, data, _ = await rn.ports.cases.latest(chat)
    assert data["pending"] is not None  # the question stays open


async def test_nonsense_reply_to_a_variant_proposal_proposes_again(saver):
    used = {"request_text": "used FixtureMake Racer", "make": MAKE, "model": "Racer", "condition": "USED",
            "year": 2025}  # fmt: skip
    llm = FakeLLM().queue("interpreter", {"request": "compare", "language": "en", "delta": {"add_cars": [used]}})
    rn = _runner(saver, llm)
    chat = str(uuid.uuid4())
    w = await rn.run_turn(chat, "a used FixtureMake Racer from 2025")
    # spec 005: the proposal is shown on the confirmation card (one card for the cars, the person and the cost)
    assert w.status == "WAITING_CONFIRMATION" and w.confirm["kind"] == "intake", (w.status, w.reply_text)
    assert [o["id"] for o in w.confirm["options"]] == ["yes", "stop"]
    assert w.confirm["card"]["cars"][0]["key"] == "car#1"
    llm.queue("interpreter", NOTHING)
    w2 = await rn.resume(chat, {"choice": "text", "text": "blah blah"})
    assert w2.status == "WAITING_CONFIRMATION" and w2.confirm["kind"] == "intake", (w2.status, w2.reply_text)
    assert w2.usage["search_calls"] == 0
    _, data, _ = await rn.ports.cases.latest(chat)
    assert data["cars"][0]["resolution"] == "PROPOSED"  # never confirmed on a guess
    llm.queue("general", "Tell me which cars to compare.")
    r = await rn.resume(chat, {"choice": "remove:car#1"})
    _, data, _ = await rn.ports.cases.latest(chat)
    assert data["cars"] == [] and r.status == "DONE"


async def test_choose_for_me_confirms_the_proposal(saver):
    used = {"request_text": "used FixtureMake Racer", "make": MAKE, "model": "Racer", "condition": "USED",
            "year": 2025}  # fmt: skip
    llm = FakeLLM().queue("interpreter", {"request": "compare", "language": "en", "delta": {"add_cars": [used]}})
    llm.responders["reporter"] = lambda s, u: "Report."
    llm.responders["extractor"] = lambda s, u: {"claims": [], "is_about_variant": True}
    rn = _runner(saver, llm)
    chat = str(uuid.uuid4())
    await rn.run_turn(chat, "a used FixtureMake Racer from 2025")
    llm.queue("interpreter", NOTHING)
    await rn.resume(chat, {"choice": "text", "text": "any"})  # typed "any" = choose for me
    _, data, _ = await rn.ports.cases.latest(chat)
    assert data["cars"][0]["resolution"] == "CONFIRMED"


async def test_unknown_model_is_reported_with_the_closest_known_ones():
    from automind.chat.application.services.identification import resolve
    from automind.chat.domain.case.casefile import CaseCar

    from .conftest import open_web_reference

    ref = open_web_reference()
    car = CaseCar(key="car#1", request_text="FixtureMake Racr", make=MAKE, model="Racr")
    ident = resolve.VariantIdentity(make=MAKE, model="Racr", generation=None, generation_years_from=None,
                                    generation_years_to=None, variant_name="?", powertrain="ICE",
                                    certainty="ambiguous", known_model=False)  # fmt: skip
    with pytest.raises(resolve.UnknownModel) as e:
        await resolve._check_known(ref, car, ident)  # noqa: SLF001
    assert e.value.closest[0] == f"{MAKE} Racer"
    known = CaseCar(key="car#1", request_text="FixtureMake Racer", make=MAKE, model="Racer")
    await resolve._check_known(ref, known, ident.model_copy(update={"model": "Racer"}))  # noqa: SLF001
