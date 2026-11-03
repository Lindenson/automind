"""Chat deletion (spec 003 US4, T048): chat-scoped data removed, shared knowledge kept, tombstone, cancel first."""

import uuid

import pytest
from sqlalchemy import func, select

from automind.application.chats import delete_chats
from automind.infrastructure.db import models as m
from automind.infrastructure.db.repositories import ChatRepo, MessageRepo
from automind.infrastructure.db.session import sessionmaker
from automind.orchestration.graph import build_graph
from automind.orchestration.runner import ChatRunner
from tests.fakes.fake_llm import FakeLLM
from tests.fakes.fixture_search import FixtureSearch

from .conftest import budget_factory, make_ports
from .test_research_flow import INTERPRET, llm_for_research
from .test_research_flow import fresh_variant as fresh_variant  # noqa: F401  (fixture)

pytestmark = pytest.mark.usefixtures("fresh_variant")
SHARED = (m.Variant, m.Document, m.Evidence, m.Claim, m.SpecValue, m.ResearchRun)
SCOPED = (m.ChatMessage, m.CaseFileRow, m.TurnEvent, m.Turn, m.ResearchJob, m.LLMCall, m.SearchCall)


async def _count(model, chat_id=None):
    async with sessionmaker()() as s:
        q = select(func.count()).select_from(model)
        if chat_id is not None:
            q = q.where(model.chat_id == chat_id)
        return (await s.execute(q)).scalar_one()


def _runner(saver, llm, search=None):
    ports = make_ports(llm=llm, search=search or FixtureSearch("racer"))
    return ChatRunner(build_graph(saver, tools=[]), ports, budget_factory(), messages=MessageRepo())


async def test_delete_removes_chat_scope_keeps_knowledge_and_tombstones(saver):
    chat_id = str(uuid.uuid4())
    llm = llm_for_research().queue("interpreter", INTERPRET).queue("reporter", "Report.")
    rn = _runner(saver, llm)
    r = await rn.run_turn(chat_id, "FixtureMake Racer for a race enthusiast")
    assert r.status == "DONE"
    assert all([await _count(t, chat_id) for t in (m.ChatMessage, m.Turn, m.ResearchJob)])
    shared = [await _count(t) for t in SHARED]
    deleted, counts = await delete_chats([chat_id], rn, ChatRepo(), saver.adelete_thread)
    assert deleted == [chat_id] and counts["chat_messages"] > 0
    for t in SCOPED:
        assert await _count(t, chat_id) == 0, t.__tablename__
    assert [await _count(t) for t in SHARED] == shared  # shared knowledge untouched (FR-029)
    assert await ChatRepo().is_deleted(chat_id)
    assert (await saver.aget_tuple({"configurable": {"thread_id": chat_id}})) is None
    # idempotent
    assert await delete_chats([chat_id], rn, ChatRepo(), saver.adelete_thread) == ([], {})
    # a new chat about the same car reuses the cached data: no searches within freshness (SC-008)
    llm2 = FakeLLM().queue("interpreter", INTERPRET).queue("reporter", "Report from the cache.")
    r2 = await _runner(saver, llm2).run_turn(str(uuid.uuid4()), "FixtureMake Racer for a race enthusiast")
    assert r2.status == "DONE" and r2.usage["search_calls"] == 0


async def test_delete_while_waiting_for_confirmation(saver):
    from tests.fakes.fake_llm import FixedEstimator

    chat_id = str(uuid.uuid4())
    llm = FakeLLM().queue("interpreter", INTERPRET)
    rn = _runner(saver, llm)
    rn.ports.estimator = FixedEstimator(eur_per_job=0.2)
    w = await rn.run_turn(chat_id, "FixtureMake Racer for a race enthusiast")
    assert w.status == "WAITING_CONFIRMATION"
    deleted, _ = await delete_chats([chat_id], rn, ChatRepo(), saver.adelete_thread)
    assert deleted == [chat_id] and await _count(m.Turn, chat_id) == 0
