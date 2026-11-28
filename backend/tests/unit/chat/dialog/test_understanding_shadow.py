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


def _context(log: Log | None, *, on: bool = True, llm: Any = None, decides: bool = False) -> TurnContext:
    ref = SimpleNamespace(prompts={"understander": "system"}, makes=None)
    ports = SimpleNamespace(llm=llm or FakeLLM(understanding()), ref=ref, understanding=log, understanding_shadow=on,
                            understanding_decides=decides)  # fmt: skip
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


# spec 013 S4 (T040): the new understanding decides typed words; the old interpreter is its fallback only

_TWO_CARS = understanding(
    goals=[{"kind": "compare"}],
    case_changes={
        "add_cars": [
            {
                "request_text": "мерседес c 200дизель 2026 года",
                "make": "Mercedes-Benz",
                "model": "C-Class",
                "year": 2026,
                "constraints": {"fuel_hint": "diesel"},
            },
            {
                "request_text": "БМВ 220д 2024 года",
                "make": "BMW",
                "model": "2 Series",
                "year": 2024,
                "constraints": {"fuel_hint": "diesel", "trim_hint": "220d"},
            },
        ]
    },
)  # chat 6e032fe4 t1: the old interpreter returned no car, the understanding both


async def test_deciding_the_understanding_is_applied_and_the_old_never_runs() -> None:
    log = Log()

    async def never() -> Reading:
        raise AssertionError("the old interpreter is only the fallback")

    reading = await read_with_shadow(_context(log, llm=FakeLLM(_TWO_CARS), decides=True), CASE, [],
                                     "сравни мерседес c 200дизель 2026 и БМВ 220д 2024", None, never)  # fmt: skip
    i = reading.interpretation
    assert i is not None and i.request == "compare" and i.language == "ru"
    assert [(c.model, c.year) for c in i.delta.add_cars] == [("C-Class", 2026), ("2 Series", 2024)]
    (rec,) = log.rows
    assert rec.intent is not None and rec.old_reading is None


async def test_deciding_a_refused_understanding_falls_back_to_the_old_reading_and_records_both() -> None:
    log = Log()
    reading = await _read(_context(log, llm=FakeLLM(RuntimeError("model down")), decides=True))
    assert reading is OLD
    (rec,) = log.rows
    assert rec.refused and rec.old_reading["interpretation"]["request"] == "compare"  # type: ignore[index]


async def test_deciding_a_bug_of_the_new_chain_falls_back_and_is_counted(monkeypatch: pytest.MonkeyPatch) -> None:
    before = _errors()

    async def bug(self: UnderstandingShadow, turn: object) -> None:
        raise KeyError("a bug")

    monkeypatch.setattr(UnderstandingShadow, "understand_words", bug)
    assert await _read(_context(Log(), decides=True)) is OLD
    assert _errors() == before + 1


async def test_deciding_buttons_keep_the_old_reading() -> None:
    log = Log()
    reading = await read_with_shadow(_context(log, decides=True), CASE, [], "", {"kind": "research_more"}, _old)
    assert reading is OLD and log.rows[0].old_reading is not None
