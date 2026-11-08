"""How a message enters the chat: the pure decision of the runner, from the open turn's status and the preset kind.

open turn      message / preset kind          entry
─────────      ─────────────────────          ─────
none           any                            START               a new turn
RUNNING        any                            BUSY_RUNNING        refused: one turn at a time
WAITING        typed message, "find it"       ANSWER              resumes the waiting turn with the text
WAITING        car edit                       REPLACE_QUESTION    the question is closed, a new turn starts
WAITING        panel edit, saved report       BUSY_QUESTION_OPEN  refused: used when the user answers
"""

from __future__ import annotations

from enum import StrEnum

from automind.chat.domain.turn import EDITS, PresetKind, TurnStatus


class Entry(StrEnum):
    """What the runner does with an incoming message."""

    START = "start"
    ANSWER = "answer"
    REPLACE_QUESTION = "replace_question"
    BUSY_RUNNING = "busy_running"
    BUSY_QUESTION_OPEN = "busy_question_open"


BUSY_REASON = {
    Entry.BUSY_RUNNING: "a turn is already running in this chat",
    Entry.BUSY_QUESTION_OPEN: "a question is open: the edit is used when the user answers",
}


def route(open_turn: TurnStatus | None, kind: PresetKind | None) -> Entry:
    """The entry for a message (`kind` None: typed by the person) given the chat's open turn, if any."""
    if open_turn is None:
        return Entry.START
    if open_turn is TurnStatus.RUNNING:
        return Entry.BUSY_RUNNING
    if kind is PresetKind.CAR_EDIT:
        return Entry.REPLACE_QUESTION
    if kind in EDITS:
        return Entry.BUSY_QUESTION_OPEN
    return Entry.ANSWER
