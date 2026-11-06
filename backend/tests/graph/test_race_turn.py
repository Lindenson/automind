"""Drag race from chat (US6): settings and prediction from the case, recomputed without research,
identical inputs → identical results (FR-038, FR-039, SC-011)."""

import json
from pathlib import Path

from sqlalchemy import select

from automind.chat.dialog.graph import build_graph
from automind.chat.dialog.runner import ChatRunner
from automind.chat.infrastructure.persistence.repositories import MessageRepo
from automind.shared.infrastructure.db import models as m
from automind.shared.infrastructure.db.session import sessionmaker
from tests.fakes.fake_llm import FakeLLM
from tests.fakes.fixture_search import FixtureSearch
from tests.golden.runner import load, seed

from .conftest import budget_factory, make_ports

GOLDEN = Path(__file__).resolve().parents[1] / "golden"
WET = {
    "request": "follow_up_question",
    "language": "en",
    "delta": {"set_race_settings": {"surface": "WET", "extra_load_kg": 150}, "set_prediction": {"winner_key": "car#1"}},
}


def runner(saver, llm):
    ports = make_ports(llm=llm, search=FixtureSearch("empty"))
    return ChatRunner(build_graph(saver, tools=[]), ports, budget_factory(), messages=MessageRepo())


def race(result):
    return next(b for b in result.blocks if b["type"] == "race_chart")


async def test_wet_race_with_passengers_and_prediction(saver, chat_id):
    await seed(load(GOLDEN / "g6_no_repeat.yaml"))
    llm = FakeLLM()
    for role, outs in json.loads((GOLDEN / "cassettes" / "g6_no_repeat" / "turn1.json").read_text()).items():
        llm.queue(role, *outs)
    dry = race(await runner(saver, llm).run_turn(chat_id, "Golf GTI Mk8 vs i30 N for a race enthusiast"))

    llm.queue("interpreter", WET).queue("answerer", "In the wet with two passengers both are slower.")
    r = await runner(saver, llm).run_turn(chat_id, "race them in the wet with 2 passengers, I bet on the Golf")
    assert r.action == "ANSWER_FROM_CONTEXT" and r.usage["search_calls"] == 0
    wet = race(r)
    assert wet["settings"]["surface"] == "WET" and wet["settings"]["extra_load_kg"] == 150
    slower = {x["car_id"]: x["t_400m"] for x in dry["results"]}
    assert all(x["t_400m"] > slower[x["car_id"]] for x in wet["results"])
    winner = next(x["car_id"] for x in wet["results"] if x["rank"] == 1)
    assert wet["prediction"] is not None and wet["prediction_correct"] == (wet["prediction"] == winner)

    async with sessionmaker()() as s:
        sims = (await s.execute(select(m.Simulation).where(m.Simulation.turn_id == r.turn_id))).scalars().all()
    assert len(sims) == 1 and sims[0].settings["surface"] == "WET" and sims[0].prediction == {"winner_key": "car#1"}

    # the same request again: identical inputs give the identical result hash
    llm.queue("interpreter", WET).queue("answerer", "Same result.")
    again = race(await runner(saver, llm).run_turn(chat_id, "and again"))
    assert again["results"] == wet["results"]
