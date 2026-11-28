"""Spec 013 S4 (T040), chat 6e032fe4 t1: with the understanding deciding, the cars it read — with their years and
models — are in the case after the first turn, and the old interpreter is not called; when the understanding
fails, the old interpreter reads the message as before."""

from __future__ import annotations

import dataclasses
import uuid

from automind.chat.dialog.graph import build_graph
from automind.chat.dialog.runner import ChatRunner
from automind.chat.infrastructure.persistence.repositories import MessageRepo
from tests.fakes.fake_llm import FakeLLM
from tests.fakes.fixture_search import FixtureSearch

from .conftest import budget_factory, make_ports

TEXT = "сравни мерседес c 200дизель 2026 года и БМВ 220д 2024 года"
CARS = {
    "language": "ru",
    "goals": [{"kind": "compare"}],
    "case_changes": {"add_cars": [
        {"request_text": "мерседес c 200дизель 2026 года", "make": "Mercedes-Benz", "model": "C-Class",
         "year": 2026, "constraints": {"fuel_hint": "diesel"}},
        {"request_text": "БМВ 220д 2024 года", "make": "BMW", "model": "2 Series", "year": 2024,
         "constraints": {"fuel_hint": "diesel", "trim_hint": "220d"}},
    ]},
}  # fmt: skip


def _runner(saver, llm: FakeLLM) -> ChatRunner:  # noqa: ANN001
    ports = dataclasses.replace(make_ports(llm=llm, search=FixtureSearch("empty")), understanding_shadow=True,
                                understanding_decides=True)  # fmt: skip
    return ChatRunner(build_graph(saver, tools=[]), ports, budget_factory(), messages=MessageRepo())


def _llm() -> FakeLLM:
    llm = FakeLLM()
    llm.responders["asker"] = lambda s, u: "Уточню."
    llm.responders["resolver"] = lambda s, u: {
        "make": "BMW",
        "model": "?",
        "generation": None,
        "generation_years_from": None,
        "generation_years_to": None,
        "variant_name": "",
        "powertrain": "ICE",
        "certainty": "ambiguous",
        "known_model": False,
    }  # identification is not what is tested here
    return llm


async def _cars(rn: ChatRunner, chat: str) -> list[tuple[str | None, str | None, int | None]]:
    _, data, _ = await rn.ports.cases.latest(chat)
    return [(c.get("make"), c.get("model"), c.get("year")) for c in data["cars"]]


async def test_the_understanding_decides_the_first_message(saver) -> None:  # noqa: ANN001
    llm = _llm().queue("understander", CARS)
    rn = _runner(saver, llm)
    chat = str(uuid.uuid4())
    await rn.run_turn(chat, TEXT)
    assert await _cars(rn, chat) == [("Mercedes-Benz", "C-Class", 2026), ("BMW", "2 Series", 2024)]
    assert "interpreter" not in llm.roles_called()


async def test_a_failing_understanding_falls_back_to_the_old_interpreter(saver) -> None:  # noqa: ANN001
    old = {"request": "compare", "language": "ru", "delta": {"add_cars": [
        {"request_text": "BMW 320d", "make": "BMW", "model": "3 Series", "year": 2024}]}}  # fmt: skip
    llm = _llm().queue("understander", RuntimeError("model down")).queue("interpreter", old)
    rn = _runner(saver, llm)
    chat = str(uuid.uuid4())
    await rn.run_turn(chat, "BMW 320d 2024")
    assert await _cars(rn, chat) == [("BMW", "3 Series", 2024)]
    assert llm.roles_called()[:2] == ["understander", "interpreter"]
