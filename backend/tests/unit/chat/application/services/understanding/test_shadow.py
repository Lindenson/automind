"""The Understander and the shadow (spec 013 T032, T034): one model call over the case, the open question with ids,
the bot's last answer and the message; the shadow's record of a turn whatever happens — words, a button, the system,
a failing model — and "the same question again"."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import pytest

from automind.chat.application.ports import StoreUnavailable
from automind.chat.application.services.understanding.shadow import ShadowTurn, UnderstandingShadow
from automind.chat.application.services.understanding.understander import Message, Understander, UnderstandError
from automind.chat.domain.case import CaseDelta, CaseFile
from automind.chat.domain.understanding.record import UnderstandingRecord

from .builder import CASE, ENGINE_Q, FakeLLM, Makes, Words, question, understanding

HISTORY = [{"role": "user", "text": "сравни Kia Sportage и Mercedes C"}, {"role": "assistant", "text": "Какой мотор?"}]
WITH_Q = CASE.model_copy(update={"pending": ENGINE_Q})


@dataclass
class Log:
    """An `UnderstandingLog` in memory; `down`: every call fails as a store that cannot be reached."""

    previous: str | None = None
    down: bool = False
    rows: list[UnderstandingRecord] = field(default_factory=list)

    async def record(self, rec: UnderstandingRecord) -> None:
        if self.down:
            raise StoreUnavailable("turn_understanding: OperationalError")
        self.rows.append(rec)

    async def for_turn(self, turn_id: str) -> UnderstandingRecord | None:
        return next((r for r in self.rows if r.turn_id == turn_id), None)

    async def last_question(self, chat_id: str) -> str | None:
        if self.down:
            raise StoreUnavailable("turn_understanding: OperationalError")
        return self.previous


def _edit(case: CaseFile, key: str, field_: str, value: str) -> CaseDelta:
    if key not in {c.key for c in case.cars}:
        raise ValueError(f"no car {key}")
    return CaseDelta.model_validate({"set_car_context": [{"target_key": key, "constraints": {"trim_hint": value}}]})


def _shadow(llm: FakeLLM, log: Log | None = None) -> UnderstandingShadow:
    return UnderstandingShadow(Understander(llm, "system", (6, 600)), Words(), Makes(), log, _edit)  # type: ignore[arg-type]


def _turn(text: str = "", preset: dict[str, object] | None = None, case: CaseFile = WITH_Q) -> ShadowTurn:
    return ShadowTurn("chat-1", "turn-1", case, HISTORY, text, preset)


async def test_the_model_sees_the_question_with_ids_and_the_last_answer() -> None:
    llm = FakeLLM(understanding())
    await Understander(llm, "system", (6, 600)).read(Message(WITH_Q, question(ENGINE_Q), HISTORY, "дизель"))  # type: ignore[arg-type]
    prompt = llm.prompts[0]
    assert f'"id": "{question(ENGINE_Q).id}"' in prompt and '"q:car#1:ENGINE:1"' in prompt
    assert "LAST ANSWER: Какой мотор?" in prompt and prompt.endswith("MESSAGE:\nдизель")


async def test_an_unreadable_output_is_refused_not_guessed() -> None:
    with pytest.raises(UnderstandError):
        await Understander(FakeLLM(ValueError("schema")), "system", (6, 600)).read(  # type: ignore[arg-type]
            Message(CASE, None, [], "hm")
        )


async def test_words_become_a_record_with_the_model_reading_and_the_intent() -> None:
    q = question(ENGINE_Q)
    u = understanding(answer_to_pending={"pending_id": q.id, "kind": "value", "evidence": "дизель"},
                      case_changes={"set_budget": {"max_eur": 30000}})  # fmt: skip
    rec = await _shadow(FakeLLM(u)).understand(_turn("дизель"))
    assert rec.source == "text" and rec.refused is None and rec.open_question_id == q.id
    assert rec.input["text"] == "дизель" and rec.input["question"]["id"] == q.id  # type: ignore[index]
    assert rec.model_raw["case_changes"]["set_budget"]["max_eur"] == 30000  # type: ignore[index]
    assert [d.check for d in rec.rejected] == ["numbers_in_message"]
    assert rec.intent["answer_to_pending"]["kind"] == "value" and rec.latency_ms is not None  # type: ignore[index]


async def test_a_failing_model_is_a_refused_record_never_an_error() -> None:
    rec = await _shadow(FakeLLM(RuntimeError("provider down"))).understand(_turn("дизель"))
    assert rec.intent is None and rec.refused == "RuntimeError: provider down"


async def test_buttons_and_the_system_need_no_model() -> None:
    llm = FakeLLM(RuntimeError("never called"))
    pick = await _shadow(llm).understand(_turn(preset={"kind": "pick", "option_id": "q:car#1:ENGINE:0"}))
    assert pick.source == "ui" and pick.intent["answer_to_pending"]["option_id"] == "q:car#1:ENGINE:0"  # type: ignore[index]
    edit = await _shadow(llm).understand(_turn(preset={"kind": "car_edit", "car_key": "car#1", "field": "trim",
                                                         "value": "GT Line"}))  # fmt: skip
    assert edit.intent["case_changes"]["set_car_context"][0]["constraints"]["trim_hint"] == "GT Line"  # type: ignore[index]
    gone = await _shadow(llm).understand(_turn(preset={"kind": "car_edit", "car_key": "car#9", "field": "trim"}))
    assert gone.refused == "car edit: no car car#9"
    saved = await _shadow(llm).understand(_turn(preset={"kind": "report_saved"}))
    assert saved.source == "system" and saved.intent["goals"] == []  # type: ignore[index]
    assert llm.prompts == []


async def test_the_same_question_open_again_is_marked_and_a_store_down_is_tolerated() -> None:
    q = question(ENGINE_Q)
    repeated = await _shadow(FakeLLM(understanding()), Log(previous=q.id)).understand(_turn("ну"))
    assert repeated.question_repeated is True
    fresh = await _shadow(FakeLLM(understanding()), Log(previous="q-other")).understand(_turn("ну"))
    assert fresh.question_repeated is False
    down = await _shadow(FakeLLM(understanding()), Log(down=True)).understand(_turn("ну"))
    assert down.question_repeated is False and down.refused is None


async def test_record_writes_through_the_log() -> None:
    log = Log()
    shadow = _shadow(FakeLLM(understanding()), log)
    await shadow.record(await shadow.understand(_turn("ну")))
    assert [r.turn_id for r in log.rows] == ["turn-1"]
    with pytest.raises(StoreUnavailable):
        await _shadow(FakeLLM(understanding()), Log(down=True)).record(log.rows[0])


class _Seq:
    """The understander's readings in order; the prompts it was given."""

    def __init__(self, *outs: object) -> None:
        self.outs, self.prompts = list(outs), []  # type: list[object], list[str]

    async def structured(self, role: str, schema: type, system: str, user: str) -> object:
        self.prompts.append(user)
        return self.outs.pop(0)


class _AnyMakes:
    def match_make(self, text: str) -> str | None:
        low = text.lower()
        return "BMW" if "bmw" in low else "Kia" if "kia" in low else None


_BOTH = understanding(goals=[{"kind": "compare"}], case_changes={"add_cars": [
    {"request_text": "Kia Sportage 2022", "make": "Kia", "model": "Sportage", "year": 2022},
    {"request_text": "BMW 320d 2024", "make": "BMW", "model": "3 Series", "year": 2024}]})  # fmt: skip


def _seq_shadow(llm: _Seq) -> UnderstandingShadow:
    return UnderstandingShadow(Understander(llm, "system", (6, 600)), Words(), _AnyMakes(), None, _edit)  # type: ignore[arg-type]


async def test_a_reading_that_missed_the_named_cars_is_read_again_with_what_it_missed() -> None:
    """Spec 013 S4 (chat 8ff3ae80): one reading in five dropped both cars; the second reading is told so."""
    llm = _Seq(understanding(goals=[{"kind": "compare"}]), _BOTH)
    rec, understood = await _seq_shadow(llm).understand_words(
        _turn("сравни Kia Sportage 2022 и BMW 320d 2024", case=CaseFile())
    )
    assert understood is not None and [c.year for c in understood.case_changes.add_cars] == [2022, 2024]
    assert len(llm.prompts) == 2 and "CHECK OF YOUR FIRST READING" in llm.prompts[1] and "Kia, BMW" in llm.prompts[1]
    assert "CHECK" not in llm.prompts[0] and rec.intent is not None


async def test_a_complete_reading_is_not_read_again_and_a_worse_second_one_is_not_kept() -> None:
    llm = _Seq(_BOTH)
    await _seq_shadow(llm).understand_words(_turn("сравни Kia Sportage 2022 и BMW 320d 2024", case=CaseFile()))
    assert len(llm.prompts) == 1
    one = understanding(goals=[{"kind": "compare"}], case_changes={"add_cars": [
        {"request_text": "Kia Sportage", "make": "Kia", "model": "Sportage"}]})  # fmt: skip
    llm = _Seq(one, understanding(goals=[{"kind": "compare"}]))
    _, understood = await _seq_shadow(llm).understand_words(_turn("Kia Sportage или BMW 320d", case=CaseFile()))
    assert understood is not None and [c.make for c in understood.case_changes.add_cars] == ["Kia"]


async def test_a_second_reading_with_cars_without_a_make_counts_by_their_words() -> None:
    no_make = understanding(goals=[{"kind": "compare"}], case_changes={"add_cars": [
        {"request_text": "Kia Sportage 2022", "model": "Sportage", "year": 2022},
        {"request_text": "BMW 320d 2024", "model": "3 Series", "year": 2024}]})  # fmt: skip
    llm = _Seq(understanding(goals=[{"kind": "compare"}]), no_make)
    _, understood = await _seq_shadow(llm).understand_words(
        _turn("сравни Kia Sportage 2022 и BMW 320d 2024", case=CaseFile())
    )
    assert understood is not None and [c.year for c in understood.case_changes.add_cars] == [2022, 2024]


async def test_a_stalled_reading_is_tried_once_more(monkeypatch: pytest.MonkeyPatch) -> None:
    from automind.chat.application.services.understanding import shadow as module

    monkeypatch.setattr(module, "READ_TIMEOUT_S", 0.05)

    class _Stall(_Seq):
        async def structured(self, role: str, schema: type, system: str, user: str) -> object:
            if not self.prompts:
                self.prompts.append(user)
                await asyncio.sleep(1)
            return await super().structured(role, schema, system, user)

    llm = _Stall(_BOTH)
    _, understood = await _seq_shadow(llm).understand_words(
        _turn("сравни Kia Sportage 2022 и BMW 320d 2024", case=CaseFile())
    )
    assert understood is not None and len(understood.case_changes.add_cars) == 2


async def test_two_stalled_readings_are_a_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    from automind.chat.application.services.understanding import shadow as module

    monkeypatch.setattr(module, "READ_TIMEOUT_S", 0.01)

    class _Never(_Seq):
        async def structured(self, role: str, schema: type, system: str, user: str) -> object:
            await asyncio.sleep(1)
            return _BOTH

    rec, understood = await _seq_shadow(_Never()).understand_words(_turn("Kia или BMW", case=CaseFile()))
    assert understood is None and rec.refused and "TimeoutError" in rec.refused
