# ruff: noqa: E501
"""Spec 007 US1 (G31, G32): the profile comes from the user's words, each field marked stated / inferred / assumed."""

import uuid

from automind.chat.dialog.graph import build_graph
from automind.chat.dialog.runner import ChatRunner
from automind.chat.infrastructure.persistence.repositories import MessageRepo
from tests.fakes.fake_llm import FakeLLM
from tests.fakes.fixture_search import FixtureSearch

from .conftest import budget_factory, make_ports
from .test_corrections import _seed_ateca


async def _first(saver, text, interpretation):
    await _seed_ateca()
    llm = FakeLLM()
    for role in ("asker", "reporter", "answerer", "general"):
        llm.responders[role] = lambda s, u: "Понял."
    llm.queue("interpreter", interpretation)
    rn = ChatRunner(build_graph(saver, tools=[]), make_ports(llm=llm, search=FixtureSearch("empty")), budget_factory(),
                    messages=MessageRepo())  # fmt: skip
    chat = str(uuid.uuid4())
    await rn.run_turn(chat, text)
    _, data, _ = await rn.ports.cases.latest(chat)
    return data


async def test_g31_persona_inferred_from_trims_and_defaults_assumed(saver):
    data = await _first(saver, "SEAT Ateca 1.5 TSI или что-то вроде M Sport?", {
        "request": "compare", "language": "ru", "persona_evidence": "M Sport",
        "delta": {"set_persona": {"persona": "PERFORMANCE", "source": "INFERRED"}, "profile_basis": {"persona": "INFERRED"},
                  "add_cars": [{"request_text": "SEAT Ateca 1.5 TSI", "make": "SEAT", "model": "Ateca"}]}})  # fmt: skip
    assert data["persona"] == "PERFORMANCE" and data["basis"]["persona"] == "INFERRED"
    assert data["profile"]["evidence"]["persona"] == "M Sport"
    assert data["ownership_years"] == 4 and data["basis"]["ownership_years"] == "ASSUMED"
    assert data["annual_km"] == 12000 and data["basis"]["annual_km"] == "ASSUMED"


async def test_g32_family_inferred_budget_stated(saver):
    data = await _first(saver, "вожу детей в школу, по выходным в горы, бюджет 30к, SEAT Ateca", {
        "request": "compare", "language": "ru", "constraints_evidence": ["бюджет 30к"],
        "delta": {"set_profile": {"family": "FAMILY", "evidence": {"family": "вожу детей в школу"}},
                  "profile_basis": {"family": "INFERRED"}, "set_usage": ["MOUNTAINS", "FAMILY"],
                  "set_budget": {"max_eur": 30000},
                  "add_cars": [{"request_text": "SEAT Ateca", "make": "SEAT", "model": "Ateca"}]}})  # fmt: skip
    assert data["profile"]["family"] == "FAMILY" and data["basis"]["family"] == "INFERRED"
    assert "MOUNTAINS" in data["usage"]
    assert data["budget"]["max_eur"] == 30000 and data["basis"]["budget"] == "STATED"
