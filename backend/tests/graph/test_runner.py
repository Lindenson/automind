"""ChatRunner lifecycle: persistent thread, interrupts, resume, busy, cancel (R2, R13, FR-043)."""

import asyncio
from typing import TypedDict

import pytest
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import interrupt

from automind.chat.dialog.runner import Busy, ChatRunner, TurnContext

from .conftest import budget_factory, make_ports


class S(TypedDict, total=False):
    user_text: str
    turns_seen: int
    reply_text: str
    action: str
    blocks: list


async def node(state: S, runtime: Runtime[TurnContext]) -> S:
    seen = state.get("turns_seen", 0) + 1
    await runtime.context.status("understanding", "thinking")
    text = state["user_text"]
    if text.startswith("confirm"):
        answer = interrupt({"kind": "variants", "action": "CONFIRM_VARIANTS", "text": "Which one?", "options": []})
        return {"turns_seen": seen, "reply_text": f"you chose {answer['text'] or answer['choice']}", "action": "REPORT"}
    if text == "slow":
        await asyncio.sleep(5)
    return {"turns_seen": seen, "reply_text": f"turn {seen}: {text}", "action": "ANSWER_FROM_CONTEXT", "blocks": []}


def graph(saver):
    g = StateGraph(S, context_schema=TurnContext)
    g.add_node("n", node)
    g.add_edge(START, "n")
    g.add_edge("n", END)
    return g.compile(checkpointer=saver)


def runner(saver, messages):
    return ChatRunner(graph(saver), make_ports(), budget_factory(), messages=messages)


async def test_persistent_thread_across_runner_instances(saver, messages, chat_id):
    r1 = await runner(saver, messages).run_turn(chat_id, "hello")
    assert r1.status == "DONE" and r1.reply_text == "turn 1: hello"
    r2 = await runner(saver, messages).run_turn(chat_id, "again")  # new runner, same checkpointer
    assert r2.reply_text == "turn 2: again"


async def test_interrupt_then_free_text_resumes_same_turn(saver, messages, chat_id):
    r = runner(saver, messages)
    w = await r.run_turn(chat_id, "confirm please")
    assert w.status == "WAITING_CONFIRMATION" and w.confirm["kind"] == "variants"
    # a new runner instance (as after a restart) resumes the interrupt with the user's text
    done = await runner(saver, messages).run_turn(chat_id, "the 150")
    assert done.status == "DONE" and done.turn_id == w.turn_id
    assert done.reply_text == "you chose the 150"
    events = await make_ports().events.replay(chat_id, 0)
    kinds = [e["type"] for e in events]
    assert "confirm_request" in kinds and kinds[-2:] == ["assistant_message", "usage"]
    assert [e["seq"] for e in events] == sorted(e["seq"] for e in events)


async def test_busy_and_cancel(saver, messages, chat_id):
    r = runner(saver, messages)
    task = asyncio.create_task(r.run_turn(chat_id, "slow"))
    await asyncio.sleep(0.5)
    with pytest.raises(Busy):
        await r.run_turn(chat_id, "second")
    assert await r.cancel(chat_id)
    res = await task
    assert res.status == "CANCELLED"
    turn = await make_ports().turns.get(res.turn_id)
    assert turn.status == "CANCELLED"
    kinds = [e["type"] for e in await make_ports().events.replay(chat_id, 0)]
    assert "turn_cancelled" in kinds
