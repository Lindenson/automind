"""Drag race from chat (US6): settings and prediction from the case, recomputed without research,
identical inputs → identical results (FR-038, FR-039, SC-011). On the same report → answer flow, spec 014 C2: a node
with `Retry.PROVIDER` writes nothing before its first model call (T112: a retried provider failure repeats no write),
and a case that keeps moving under a node fails the turn with a notice (T113, owner's decision G3)."""

import importlib
import inspect
import json
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from automind.chat.application.ports import VersionConflict
from automind.chat.dialog.contract import Retry
from automind.chat.dialog.graph import build_graph, contracted_nodes
from automind.chat.dialog.runner import ChatRunner
from automind.chat.infrastructure.persistence.repositories import CaseRepo, EventRepo, MessageRepo
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


# --- spec 014 C2 ----------------------------------------------------------------------------------------------------

DECORATOR = importlib.import_module("automind.chat.dialog.contract.node")  # the module, not the exported `node`
RETRIED = {n.name for n in contracted_nodes() if n.retry is Retry.PROVIDER}
# what the stores write (the event bus is the client's progress stream, not a store: a retry shows it again)
WRITES = {"cases": {"save_version"}, "computations": {"record"}, "messages": {"save"},
          "jobs": {"create", "mark", "skip_open"}, "feasibility": {"save_checks"}}  # fmt: skip


class Guard:
    """Armed while a retried node has not called the model yet; a store write then fails the test."""

    def __init__(self) -> None:
        self.node, self.armed, self.checked = "", False, set()

    def enter(self, name: str) -> None:
        self.node, self.armed = name, name in RETRIED

    def write(self, what: str) -> None:
        assert not self.armed, f"{self.node}: {what} before its first model call (a retry would repeat it)"
        if self.node in RETRIED:
            self.checked.add(self.node)


class Watched:
    """A port seen by the guard: a store's writes are checked, any model call disarms it."""

    def __init__(self, inner: Any, guard: Guard, writes: set[str], model: bool = False) -> None:
        self.inner, self.guard, self.writes, self.model = inner, guard, writes, model

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self.inner, name)
        if not inspect.iscoroutinefunction(attr) or not (self.model or name in self.writes):
            return attr

        async def call(*args: Any, **kwargs: Any) -> Any:
            if self.model:
                self.guard.armed = False
            else:
                self.guard.write(name)
            return await attr(*args, **kwargs)

        return call


def _watched_runner(saver, llm, guard: Guard) -> ChatRunner:
    ports = make_ports(llm=llm, search=FixtureSearch("empty"))
    for port, writes in WRITES.items():
        if getattr(ports, port) is not None:
            setattr(ports, port, Watched(getattr(ports, port), guard, writes))
    ports.llm = Watched(ports.llm, guard, set(), model=True)
    return ChatRunner(build_graph(saver, tools=[]), ports, budget_factory(), messages=MessageRepo())


async def test_a_retried_node_writes_nothing_before_its_model_call(saver, chat_id, monkeypatch):
    guard = Guard()
    visit = DECORATOR.visit
    monkeypatch.setattr(DECORATOR, "visit", lambda name: (guard.enter(name), visit(name))[1])
    await seed(load(GOLDEN / "g6_no_repeat.yaml"))
    llm = FakeLLM()
    for role, outs in json.loads((GOLDEN / "cassettes" / "g6_no_repeat" / "turn1.json").read_text()).items():
        llm.queue(role, *outs)
    r1 = await _watched_runner(saver, llm, guard).run_turn(chat_id, "Golf GTI Mk8 vs i30 N for a race enthusiast")
    llm.queue("interpreter", WET).queue("answerer", "In the wet with two passengers both are slower.")
    r2 = await _watched_runner(saver, llm, guard).run_turn(chat_id, "race them in the wet with 2 passengers")
    assert (r1.action, r2.action) == ("REPORT", "ANSWER_FROM_CONTEXT")
    assert guard.checked >= {"report", "answer"}  # both wrote (computations, the case) — after the model


class MovingCases(CaseRepo):
    """The store as if the case panel saved before every save of the turn."""

    async def save_version(self, chat_id, data, changed_by, change_log, *, expected):
        version, current, _ = await self.latest(chat_id)
        await super().save_version(chat_id, current or {}, "user", ["panel edit"], expected=version)
        return await super().save_version(chat_id, data, changed_by, change_log, expected=expected)


async def test_a_case_moving_twice_under_a_node_fails_the_turn_with_a_notice(saver, chat_id):
    await seed(load(GOLDEN / "g6_no_repeat.yaml"))
    llm = FakeLLM()
    for role, outs in json.loads((GOLDEN / "cassettes" / "g6_no_repeat" / "turn1.json").read_text()).items():
        llm.queue(role, *outs)
    ports = make_ports(llm=llm, search=FixtureSearch("empty"))
    ports.cases = MovingCases()
    rn = ChatRunner(build_graph(saver, tools=[]), ports, budget_factory(), messages=MessageRepo())
    with pytest.raises(VersionConflict):
        await rn.run_turn(chat_id, "Golf GTI Mk8 vs i30 N for a race enthusiast")
    events = await EventRepo().since(chat_id, 0)
    errors = [e.payload for e in events if e.type == "error"]
    assert len(errors) == 1 and "changed elsewhere" in errors[0]["text"]
    assert not [e for e in events if e.type == "case_file"]  # apply_delta never saved: two runs, two conflicts
    version, _, by = await CaseRepo().latest(chat_id)
    assert (version, by) == (2, "user")  # only the panel's two edits
