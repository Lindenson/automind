"""A turn's lifecycle as a state machine, and the named inputs that start one (code-shape "States, not words").

    start ──► RUNNING ──► DONE | FAILED
                 │  ▲
       question  ▼  │ answer
              WAITING ──► CANCELLED   (also from RUNNING: cancel, or a car edit replacing the open question)

`TurnStatus` is a `StrEnum`: it equals the string stored in `turns.status`, so rows and events keep their values.
Every status write goes through `check_move`, which refuses a step the table does not have (`IllegalTransition`).
`JobStatus` is the life of a turn's research job, `PresetKind` names the requests a button makes without the
interpreter, `Role` the author of a stored message.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum


class TurnStatus(StrEnum):
    """Where a turn is in its life."""

    RUNNING = "RUNNING"  # the graph works (also after a restart, before it resumes)
    WAITING = "WAITING_CONFIRMATION"  # paused at a question; the next answer or message resumes it
    DONE = "DONE"  # answered (also a plain "limit reached" / "provider down" answer)
    CANCELLED = "CANCELLED"  # stopped by the user, or its open question replaced by a car edit
    FAILED = "FAILED"  # an error the turn could not turn into an answer


OPEN = frozenset({TurnStatus.RUNNING, TurnStatus.WAITING})
FINAL = frozenset({TurnStatus.DONE, TurnStatus.CANCELLED, TurnStatus.FAILED})

TRANSITIONS: Mapping[TurnStatus, frozenset[TurnStatus]] = {
    TurnStatus.RUNNING: frozenset({TurnStatus.RUNNING, TurnStatus.WAITING, *FINAL}),  # RUNNING again: a restart
    TurnStatus.WAITING: frozenset({TurnStatus.RUNNING, TurnStatus.CANCELLED}),
    TurnStatus.DONE: frozenset(),
    TurnStatus.CANCELLED: frozenset(),
    TurnStatus.FAILED: frozenset(),
}


class IllegalTransition(RuntimeError):
    """A status write the lifecycle does not allow (a bug in the caller, never a user's doing)."""


def check_move(current: TurnStatus, to: TurnStatus) -> None:
    """Refuse a step from `current` to `to` that TRANSITIONS does not list."""
    if to not in TRANSITIONS[current]:
        raise IllegalTransition(f"turn status {current} -> {to} is not allowed")


class JobStatus(StrEnum):
    """Where a research job of a turn (one car × area in a round) is."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"  # each start counts an attempt
    DONE = "DONE"  # results stored (a resumed turn does not run it again)
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"  # its turn was cancelled or its question replaced


class PresetKind(StrEnum):
    """A request a button already knows: the turn skips the interpretation call."""

    RESEARCH_MORE = "research_more"  # "find it": research given cars and areas
    CAR_EDIT = "car_edit"  # "Change" on a car (generation, engine, gearbox, trim, not this car, remove)
    RESCORE = "rescore"  # an edit in the case panel (weights, profile)
    REPORT_SAVED = "report_saved"  # after a turn timeout: the report from the data already saved


EDITS = frozenset({PresetKind.CAR_EDIT, PresetKind.RESCORE, PresetKind.REPORT_SAVED})  # not the person's words


def preset_kind(preset: Mapping[str, object] | None) -> PresetKind | None:
    """The kind of a preset as the graph state holds it (a plain dict), None for a typed message."""
    kind = (preset or {}).get("kind")
    return PresetKind(kind) if isinstance(kind, str) and kind in PresetKind else None


class Role(StrEnum):
    """Who a stored message is from."""

    USER = "user"
    ASSISTANT = "assistant"
    EDIT = "edit"  # a panel edit: kept apart from the person's words (the chat does not show it)
