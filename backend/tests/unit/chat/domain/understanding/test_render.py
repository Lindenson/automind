"""`turn show` text (spec 013 T035): every part of the record a person needs to read a complaint."""

from __future__ import annotations

from automind.chat.domain.understanding.intent import Override
from automind.chat.domain.understanding.record import Dropped, UnderstandingRecord
from automind.chat.domain.understanding.render import render_understanding


def test_the_chain_of_a_turn_is_readable() -> None:
    rec = UnderstandingRecord(
        chat_id="c", turn_id="t", source="text", input={"text": "да, но дизель", "question": {"id": "q-1"}},
        open_question_id="q-1", question_repeated=True, model="m", prompt_version="understander@v1", latency_ms=700,
        model_raw={"language": "ru"}, rejected=(Dropped(check="numbers_in_message", field="set_budget", why="no"),),
        overrides=(Override(rule="stale_pending", field="answer_to_pending", before={"kind": "yes"}, why="old"),),
        intent={"language": "ru"}, old_reading={"interpretation": {"request": "confirm_yes"}},
    )  # fmt: skip
    text = render_understanding(rec)
    for part in ("the same question as the turn before", '"text": "да, но дизель"', '"id": "q-1"', "understander@v1",
                 "numbers_in_message set_budget: no", 'stale_pending answer_to_pending: {"kind": "yes"} → null (old)',
                 'intent: {"language": "ru"}', "old interpreter (decided the turn)", "confirm_yes"):  # fmt: skip
        assert part in text, part
    assert render_understanding(None) == "no understanding recorded for this turn"


def test_empty_fields_are_left_out() -> None:
    rec = UnderstandingRecord(chat_id="c", turn_id="t", source="text", input={"text": "stop", "question": None},
                              intent={"goals": [{"kind": "stop", "focus_cars": [], "question": None}],
                                      "answer_to_pending": None, "case_changes": {"add_cars": []}})  # fmt: skip
    assert 'intent: {"goals": [{"kind": "stop"}]}' in render_understanding(rec)
