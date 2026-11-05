"""Spec 010 US1 (T019): every turn leaves a scored outcome; the next message tells how the previous answer landed."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from automind.infrastructure import db
from automind.infrastructure.db.models import Feedback, TurnOutcome
from automind.infrastructure.db.outcomes import OutcomeRepo
from automind.infrastructure.db.repositories import MessageRepo
from automind.infrastructure.usage_callback import UsageCallbackHandler, current_prompt, prompt_identity
from automind.orchestration.graph import build_graph
from automind.orchestration.runner import ChatRunner
from tests.fakes.fake_llm import FakeLLM
from tests.fakes.fixture_search import FixtureSearch

from .conftest import budget_factory, make_ports


def _runner(saver, llm):
    ports = make_ports(llm=llm, search=FixtureSearch("empty"))
    ports.outcomes = OutcomeRepo(ports.ref.outcome, "test")
    return ChatRunner(build_graph(saver, tools=[]), ports, budget_factory(), messages=MessageRepo())


def _general(relation: str = "continues") -> dict:
    return {"request": "general_question", "language": "en", "relation": relation, "delta": {}}


async def _outcomes(chat: str) -> list[TurnOutcome]:
    async with db.sessionmaker()() as s:
        q = select(TurnOutcome).where(TurnOutcome.chat_id == chat).order_by(TurnOutcome.created_at)
        return list((await s.execute(q)).scalars())


async def test_rephrase_marks_the_previous_turn_and_thanks_raises_it(saver):
    llm = FakeLLM()
    llm.responders["general"] = lambda s, u: "A turbo uses exhaust gas to compress intake air."
    rn = _runner(saver, llm)
    chat = str(uuid.uuid4())
    llm.queue("interpreter", _general())
    await rn.run_turn(chat, "how does a turbo work?")
    llm.queue("interpreter", _general("rephrase"))
    await rn.run_turn(chat, "I mean, why does it lag?")
    llm.queue("interpreter", _general("thanks"))
    await rn.run_turn(chat, "thanks!")
    rows = await _outcomes(chat)
    assert len(rows) == 3
    first, second, third = rows
    assert first.relation_next == "rephrase" and "not_understood" in first.failure_classes and first.score < 0.5
    assert second.relation_next == "thanks" and second.score > 0.5 and not second.failure_classes
    assert third.relation_next is None and third.status == "DONE"
    assert first.path and first.path[0] == "load_case" and "interpret" in first.path
    async with db.sessionmaker()() as s:
        kinds = [f.kind for f in (await s.execute(select(Feedback).where(Feedback.chat_id == chat))).scalars()]
    assert kinds == ["rephrase"]


async def test_failed_turn_is_recorded_as_process_failure(saver):
    llm = FakeLLM()

    def boom(s: str, u: str) -> str:
        raise RuntimeError("model exploded")

    llm.responders["general"] = boom
    rn = _runner(saver, llm)
    chat = str(uuid.uuid4())
    llm.queue("interpreter", _general())
    with pytest.raises(RuntimeError):
        await rn.run_turn(chat, "how does a turbo work?")
    rows = await _outcomes(chat)
    assert len(rows) == 1 and rows[0].status == "FAILED"
    assert rows[0].failure_classes == ["process_failure"] and rows[0].score <= 0.1


def test_model_calls_carry_prompt_identity_and_fallback():
    h = UsageCallbackHandler("interpreter", "google_genai:gemini-3.1-flash-lite", prices=None,  # type: ignore[arg-type]
                             repo=object(), primary="google_genai:gemini-3.6-flash")  # type: ignore[arg-type]  # fmt: skip
    token = current_prompt.set(prompt_identity("interpreter", "<!-- prompt: interpreter v3 -->\nRules"))
    try:
        ident = h._identity()  # noqa: SLF001
    finally:
        current_prompt.reset(token)
    assert ident["fallback"] is True and ident["primary_model"] == "google_genai:gemini-3.6-flash"
    assert ident["prompt_name"] == "interpreter" and ident["prompt_version"] == "v3" and len(ident["prompt_hash"]) == 12
