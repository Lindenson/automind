"""Spec 005 US1 (FR-001–FR-004): every reply moves the identification forward; no question is sent twice; after
two attempts on one item the hub proposes or offers removal; the same make/model repeated triggers a new lookup
(chat 5be54966: "I don't know a car called «byd»" four times)."""

import re
import uuid

from automind.infrastructure.db.repositories import MessageRepo
from automind.orchestration.graph import build_graph
from automind.orchestration.runner import ChatRunner
from tests.fakes.fake_llm import FakeLLM
from tests.fakes.fixture_search import FixtureSearch

from .conftest import budget_factory, forget_make, make_ports

ENGLISH = re.compile(r"\b(the|which|did you mean|make and model|I don't know)\b", re.I)
UNKNOWN_SEAL = {"make": "BYD", "model": "Seal U", "generation": None, "generation_years_from": None,
                "generation_years_to": None, "variant_name": "", "powertrain": "PHEV",
                "certainty": "ambiguous", "known_model": False}  # fmt: skip


def _ru(delta: dict) -> dict:
    return {"request": "compare", "language": "ru", "delta": delta}


def _runner(saver, llm):
    ports = make_ports(llm=llm, search=FixtureSearch("empty"))
    return ChatRunner(build_graph(saver, tools=[]), ports, budget_factory(), messages=MessageRepo())


def _questions(text: str) -> str:
    return text.split("\n\n")[-1]  # the code-written questions follow the acknowledgement


async def test_unknown_brand_model_is_looked_up_again_and_never_asked_the_same_way(saver):
    await forget_make("BYD")
    llm = FakeLLM()
    llm.responders["asker"] = lambda s, u: "Понял: сравниваем BYD с другой машиной для семьи."
    llm.queue("interpreter", _ru({"add_cars": [{"request_text": "byd", "make": "BYD"}]}))
    rn = _runner(saver, llm)
    chat = str(uuid.uuid4())
    r1 = await rn.run_turn(chat, "насколько хороша byd — найди соответствующую модель")
    assert r1.action == "ASK", r1.reply_text
    q1 = _questions(r1.reply_text)
    assert "BYD" in q1 and "byd»" not in q1 and not ENGLISH.search(q1), q1
    # the user names the model; it is unknown to the catalog and the resolver cannot place it
    llm.queue("interpreter", _ru({"set_car_context": [{"target_key": "car#1", "make": "BYD", "model": "Seal U"}]}))
    llm.queue("resolver", UNKNOWN_SEAL)
    r2 = await rn.run_turn(chat, "BYD Seal U допустим")
    assert r2.action == "ASK"
    q2 = _questions(r2.reply_text)
    assert "BYD Seal U" in q2 and q2 != q1 and not ENGLISH.search(q2), q2
    assert "make and model" not in r2.reply_text
    # the same make and model again: a new lookup (not "not understood"), and other words
    calls = llm.roles_called().count("resolver")
    llm.queue("interpreter", _ru({"set_car_context": [{"target_key": "car#1", "make": "BYD", "model": "Seal U"}]}))
    llm.queue("resolver", UNKNOWN_SEAL)
    r3 = await rn.run_turn(chat, "ну дак сравни byd seal u")
    assert llm.roles_called().count("resolver") == calls + 1
    q3 = _questions(r3.reply_text)
    assert q3 not in (q1, q2), q3
    assert "не понял" not in r3.reply_text.lower()
    _, data, _ = await rn.ports.cases.latest(chat)
    assert data["cars"][0]["resolution"] != "UNKNOWN_MODEL"  # never sticky
    hashes = data["intake"]["last_questions"]
    assert len(hashes) == len(set(hashes))  # no question text twice
    assert r3.usage["search_calls"] <= 8


async def test_nonsense_replies_rephrase_then_offer_removal(saver):
    await forget_make("BYD")
    llm = FakeLLM()
    llm.responders["asker"] = lambda s, u: "Понял."
    nothing = _ru({})
    llm.queue("interpreter", _ru({"add_cars": [{"request_text": "byd", "make": "BYD"}]}), nothing, nothing)
    rn = _runner(saver, llm)
    chat = str(uuid.uuid4())
    r1 = await rn.run_turn(chat, "byd для семьи")
    r2 = await rn.run_turn(chat, "qwerty asdf")
    r3 = await rn.run_turn(chat, "zzz")
    q = [_questions(r.reply_text) for r in (r1, r2, r3)]
    assert len(set(q)) == 3, q  # first wording, the rephrase, then "remove or choose"
    assert all(r.action == "ASK" for r in (r1, r2, r3))
    chips = [i["label"] for i in next(b for b in r3.blocks if b["type"] == "quick_replies")["items"]]
    assert any("Убрать" in c for c in chips) and any("Выбери сам" in c for c in chips), chips
    assert r3.usage["search_calls"] == 0 and "resolver" not in llm.roles_called()
