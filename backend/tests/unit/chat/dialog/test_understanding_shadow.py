"""The S3 shadow in the interpret node (spec 013 T034): off, the old reading alone; on, the new understanding runs
beside it and the turn's record keeps what the old one read; neither a failing store nor a bug of the shadow breaks
the turn, and a failing old reading still fails it."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from automind.chat.application.services.interpretation.contracts import Interpretation, Reading
from automind.chat.application.services.understanding.shadow import UnderstandingShadow
from automind.chat.dialog.turn.context import TurnContext
from automind.chat.dialog.understanding_shadow import read_with_shadow
from automind.shared.infrastructure.metrics import understanding as metrics
from tests.unit.chat.application.services.understanding.builder import CASE, FakeLLM, understanding
from tests.unit.chat.application.services.understanding.test_shadow import Log

OLD = Reading(Interpretation(request="compare", language="ru"), "ru")


def _context(log: Log | None, *, on: bool = True, llm: Any = None) -> TurnContext:
    ref = SimpleNamespace(prompts={"understander": "system"}, makes=None)
    ports = SimpleNamespace(llm=llm or FakeLLM(understanding()), ref=ref, understanding=log, understanding_shadow=on)
    return TurnContext(ports=ports, chat_id="chat-1", turn_id="turn-1", budget=None)  # type: ignore[arg-type]


async def _old() -> Reading:
    return OLD


async def _read(c: TurnContext, old: Any = _old) -> Reading:
    return await read_with_shadow(c, CASE, [], "сравни их", None, old)


def _errors() -> float:
    return metrics.RECORD_ERRORS._value.get()  # noqa: SLF001


async def test_off_the_old_reading_alone() -> None:
    log = Log()
    llm = FakeLLM(RuntimeError("never called"))
    assert await _read(_context(log, on=False, llm=llm)) is OLD
    assert log.rows == [] and llm.prompts == []


async def test_on_the_turn_records_both_readings() -> None:
    log = Log()
    assert await _read(_context(log)) is OLD
    (rec,) = log.rows
    assert rec.turn_id == "turn-1" and rec.intent is not None
    assert rec.old_reading["interpretation"]["request"] == "compare"  # type: ignore[index]


async def test_a_failing_old_reading_fails_the_turn_and_stops_the_shadow() -> None:
    log = Log()

    async def boom() -> Reading:
        await asyncio.sleep(0)
        raise RuntimeError("provider down")

    with pytest.raises(RuntimeError, match="provider down"):
        await _read(_context(log), boom)
    await asyncio.sleep(0)
    assert log.rows == []


async def test_a_store_down_or_a_bug_of_the_shadow_never_breaks_the_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    before = _errors()
    assert await _read(_context(Log(down=True))) is OLD

    async def bug(self: UnderstandingShadow, turn: object) -> None:
        raise KeyError("a bug")

    monkeypatch.setattr(UnderstandingShadow, "understand", bug)
    assert await _read(_context(Log())) is OLD
    assert _errors() == before + 2
