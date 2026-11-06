"""The real turn graph keeps the case and a pending confirmation across runner restarts (FR-010, R2)."""

import json
from pathlib import Path

from automind.chat.dialog.graph import build_graph
from automind.chat.dialog.runner import ChatRunner
from automind.chat.infrastructure.persistence.repositories import MessageRepo
from tests.fakes.fake_llm import FakeLLM
from tests.golden.runner import load, seed

from .conftest import budget_factory, make_ports

G1 = Path(__file__).resolve().parents[1] / "golden"


def cassette(turn: int) -> dict:
    return json.loads((G1 / "cassettes" / "g1_bigster_prado" / f"turn{turn}.json").read_text())


def new_runner(saver, llm):
    from tests.fakes.fixture_search import FixtureSearch

    return ChatRunner(
        build_graph(saver, tools=[]),
        make_ports(llm=llm, search=FixtureSearch("empty")),
        budget_factory(),
        messages=MessageRepo(),
    )


async def test_case_and_interrupt_survive_runner_restart(saver, chat_id):
    await seed(load(G1 / "g1_bigster_prado.yaml"))
    llm = FakeLLM()
    for t in (1, 2):
        for role, outs in cassette(t).items():
            llm.queue(role, *outs)
    a = new_runner(saver, llm)
    r1 = await a.run_turn(
        chat_id,
        "I don't want to spend too much, but I don't want rubbish either. "
        "A brand-new Dacia Bigster or a used Land Cruiser Prado?",
    )
    assert r1.action == "ASK"
    r2 = await a.run_turn(chat_id, "about 10 years old, the 150")
    assert r2.status == "WAITING_CONFIRMATION"

    # "restart": a new runner and graph on the same checkpointer resume the pending confirmation
    llm2 = FakeLLM()
    for role, outs in cassette(3).items():
        llm2.queue(role, *outs)
    b = new_runner(saver, llm2)
    r3 = await b.resume(chat_id, {"choice": "confirm"})
    assert r3.status == "DONE" and r3.action == "REPORT" and r3.turn_id == r2.turn_id
    _, case, _ = await make_ports().cases.latest(chat_id)
    assert [c["resolution"] for c in case["cars"]] == ["CONFIRMED", "CONFIRMED"]  # spec 005: the card confirms both
    assert case["persona"] == "BUYER" and case["cars"][1]["year"] == 2016
