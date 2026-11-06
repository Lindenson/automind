"""Spec 007 J (T073 to T076): panel edits never write a user message, never get lost, never fight a turn."""

import asyncio
from types import SimpleNamespace

import pytest

from automind.chat.application.ports import VersionConflict
from automind.chat.dialog.nodes.common import history
from automind.chat.domain.case.casefile import CaseFile
from automind.chat.infrastructure.persistence.repositories import CaseRepo, MessageRepo, TurnRepo
from automind.delivery.web import rest
from automind.delivery.web.rest import CasePatch
from tests.fakes.fake_llm import FakeLLM

from .test_rescore import _reported
from .test_weights_recompute import runner


class _Chats:
    async def ensure(self, chat_id):
        return None


def _st(rn):
    return SimpleNamespace(cases=CaseRepo(), turns=TurnRepo(), runner=rn, bus=rn.ports.events, chats=_Chats())


async def _settle(chat_id):
    for _ in range(200):
        w = rest._WORKERS.get(chat_id)
        if w is None or w.done():
            return
        await asyncio.sleep(0.05)
    raise AssertionError("the rescore worker did not finish")


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    monkeypatch.setattr(rest, "RESCORE_POLL_S", 0.05)


async def test_rescore_writes_no_user_message_and_the_interpreter_never_sees_it(saver, chat_id):
    llm = FakeLLM()
    await _reported(saver, chat_id, llm)
    rn = runner(saver, llm)
    llm.queue("reporter", "Reliability and cost weigh most now.")
    saved = await rest.save_patch(_st(rn), chat_id, CasePatch(persona="BUYER"))
    assert saved is not None
    _, new, changes = saved
    assert rest._want_rescore(_st(rn), chat_id, new, changes) == "started"
    await _settle(chat_id)
    msgs = await MessageRepo().history(chat_id)
    assert not [m for m in msgs if m.role == "user" and m.text.startswith("↻")]
    assert [m for m in msgs if m.role == "edit"]  # kept for the record, hidden
    ctx = SimpleNamespace(chat_id=chat_id, ports=SimpleNamespace(messages=MessageRepo()))
    assert all(not h["text"].startswith("↻") for h in await history(ctx))
    assert msgs[-1].role == "assistant"  # the rescore did run


async def test_edit_during_a_running_turn_is_queued_then_applied_and_rescored(saver, chat_id):
    llm = FakeLLM()
    await _reported(saver, chat_id, llm)
    rn = runner(saver, llm)
    st = _st(rn)
    version, _, _ = await st.cases.latest(chat_id)
    busy = await st.turns.start(chat_id, None, version)  # someone's message is being answered
    assert await rest.save_patch(st, chat_id, CasePatch(persona="BUYER")) is None  # not written under the turn
    rest._QUEUED.setdefault(chat_id, []).append(CasePatch(persona="BUYER"))
    rest._kick(st, chat_id)
    await asyncio.sleep(0.2)
    _, data, _ = await st.cases.latest(chat_id)
    assert CaseFile.model_validate(data).persona != "BUYER"  # still waiting for the turn
    llm.queue("reporter", "Updated for a buyer.")
    await st.turns.update(busy.id, status="DONE")
    await _settle(chat_id)
    _, data, _ = await st.cases.latest(chat_id)
    assert CaseFile.model_validate(data).persona == "BUYER"
    msgs = await MessageRepo().history(chat_id)
    assert msgs[-1].role == "assistant" and msgs[-2].role == "edit"


async def test_two_edits_on_the_same_version_keep_both(saver, chat_id):
    llm = FakeLLM()
    await _reported(saver, chat_id, llm)
    repo = CaseRepo()
    version, data, _ = await repo.latest(chat_id)
    await repo.save_if_idle(chat_id, data, "user", ["first"], expected_version=version)
    with pytest.raises(VersionConflict):
        await repo.save_if_idle(chat_id, data, "user", ["stale"], expected_version=version)
    st = _st(runner(saver, llm))
    await rest.save_patch(st, chat_id, CasePatch(annual_km=21000))
    await rest.save_patch(st, chat_id, CasePatch(ownership_years=9))
    _, data, _ = await repo.latest(chat_id)
    c = CaseFile.model_validate(data)
    assert c.annual_km == 21000 and c.ownership_years == 9
