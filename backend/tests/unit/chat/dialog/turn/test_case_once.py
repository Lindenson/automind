"""Spec 014 C2: the case file once per run of the graph (T110) and the owner's decision G3 (T113) — a node whose save
meets a case that moved on runs once more from a fresh read; a second conflict fails the turn with a notice."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import SkipValidation

from automind.chat.application.ports import VersionConflict
from automind.chat.dialog.contract import NodeIn, NodeOut, node
from automind.chat.dialog.turn.cached import Cached
from automind.chat.dialog.turn.context import TurnContext
from automind.chat.dialog.turn.endings import ending_for, user_error_text


class Cases:
    """An in-memory case store with the port's version check; `moves_on` other writers save before each of ours."""

    def __init__(self, data: dict[str, Any] | None = None, moves_on: int = 0) -> None:
        self.version, self.data, self.reads, self.moves_on = (1 if data else 0), data, 0, moves_on

    async def latest(self, chat_id: str) -> tuple[int, dict[str, Any] | None, str | None]:
        self.reads += 1
        return self.version, self.data, None

    async def save_version(self, chat_id: str, data: dict[str, Any], changed_by: str, change_log: list[str], *,
                           expected: int) -> int:  # fmt: skip
        if self.moves_on:  # a panel edit (or another writer) got there first
            self.moves_on -= 1
            self.version, self.data = self.version + 1, {**(self.data or {}), "depth": "DEEP"}
        if expected != self.version:
            raise VersionConflict(self.version)
        self.version, self.data = self.version + 1, data
        return self.version


def _ctx(cases: Cases) -> TurnContext:
    return TurnContext(SimpleNamespace(cases=cases), "chat-c2", "turn-c2", budget=None)  # type: ignore[arg-type]


async def test_the_case_is_read_once_per_run_and_each_read_is_a_new_object() -> None:
    cases = Cases({"depth": "QUICK"})
    c = _ctx(cases)
    first = await c.case()
    first.depth = "DEEP"  # a node changes its copy without saving
    assert (await c.case()).depth == "QUICK" and await c.case_version() == 1 and cases.reads == 1


async def test_a_save_keeps_the_cache_current_and_the_next_save_expects_its_version() -> None:
    cases = Cases({"depth": "QUICK"})
    c = _ctx(cases)
    case = await c.case()
    case.depth = "DEEP"
    assert await c.save_case(case, ["deeper"], publish=False) == 2
    assert (await c.case()).depth == "DEEP" and await c.case_version() == 2
    assert await c.save_case(await c.case(), [], publish=False) == 3 and cases.reads == 1


async def test_the_cached_case_iterates_its_dicts_like_a_store_read() -> None:
    c = _ctx(Cases())
    case = await c.case()
    case.weights = {"performance": 0.5, "price": 0.3, "fun": 0.2}
    await c.save_case(case, [], publish=False)
    assert list((await c.case()).weights) == ["fun", "price", "performance"]  # jsonb: by length, then bytes


async def test_a_stale_save_is_a_conflict_and_drops_the_cached_case() -> None:
    cases = Cases({"depth": "QUICK"}, moves_on=1)
    c = _ctx(cases)
    with pytest.raises(VersionConflict):
        await c.save_case(await c.case(), ["from a stale read"], publish=False)
    assert (await c.case()).depth == "DEEP" and await c.case_version() == 2 and cases.reads == 2


async def test_parallel_readers_share_one_read() -> None:
    reads = 0

    async def load() -> int:
        nonlocal reads
        reads += 1
        await asyncio.sleep(0)
        return 7

    cached = Cached(load)
    assert await asyncio.gather(cached.get(), cached.get(), cached.get()) == [7, 7, 7] and reads == 1


# --- G3: once more from a fresh read, then the turn fails -----------------------------------------------------------


class Nothing(NodeIn):
    pass


class Asked(NodeOut):
    reply_text: str
    blocks: SkipValidation[list[dict[str, object]]] = []


RUNS: list[str] = []


@node("ask", reads=Nothing, writes=Asked)
async def _deepen(inp: Nothing, c: TurnContext) -> Asked:
    case = await c.case()
    RUNS.append(case.depth)
    case.depth = "QUICK" if case.depth == "DEEP" else "DEEP"
    return Asked(reply_text=f"v{await c.save_case(case, ['toggled'], publish=False)}")


async def test_a_conflict_runs_the_node_once_more_from_a_fresh_read() -> None:
    RUNS.clear()
    cases = Cases({"depth": "STANDARD"}, moves_on=1)
    update = await _deepen({}, SimpleNamespace(context=_ctx(cases)))
    assert RUNS == ["STANDARD", "DEEP"]  # the second run saw the other writer's case
    assert update == {"reply_text": "v3"} and cases.data["depth"] == "QUICK" and cases.reads == 2


async def test_a_second_conflict_fails_the_turn_with_a_notice() -> None:
    RUNS.clear()
    cases = Cases({"depth": "STANDARD"}, moves_on=2)
    with pytest.raises(VersionConflict) as conflict:
        await _deepen({}, SimpleNamespace(context=_ctx(cases)))
    assert len(RUNS) == 2 and cases.version == 3  # ours never saved; the other writer's two versions stay
    assert ending_for(conflict.value) is None  # not an early ending: the turn FAILS …
    assert "changed elsewhere" in user_error_text(conflict.value)  # … and the error event says why
