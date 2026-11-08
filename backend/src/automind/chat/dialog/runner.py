"""Per-chat turn runner (research R2, R13, R14; FR-040..FR-044): the entry point of the web layer.

One LangGraph thread per chat (`thread_id = chat_id`) on the Postgres checkpointer, so the case file, open questions
and context survive restarts. The runner decides what a message does (`turn.entry.route`: start, answer the open
question, replace it, or busy), keeps one task per chat, and hands each run to `turn.execution.TurnExecution`, which
ends the turn whatever happens. The lifecycle (`chat.domain.turn.TRANSITIONS`) is checked on every status write.

Errors: `Busy` when the chat cannot take the message now (a turn runs, or an edit while a question is open);
`NothingToConfirm` when an answer arrives without an open question; a store's `StoreUnavailable` propagates.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from langgraph.types import Command

from automind.chat.application.ports import MessageRepo, Ports, TurnBusy, TurnRecord
from automind.chat.dialog.turn.context import TurnContext
from automind.chat.dialog.turn.entry import BUSY_REASON, Entry, route
from automind.chat.dialog.turn.execution import BudgetFactory, TurnExecution, TurnGraph
from automind.chat.dialog.turn.journal import LiveTurn, TurnJournal
from automind.chat.dialog.turn.outcome import OutcomeRecorder
from automind.chat.dialog.turn.replies import TurnReplies, TurnResult
from automind.chat.domain.turn import EDITS, PresetKind, Role, TurnStatus, preset_kind

__all__ = ["Busy", "ChatRunner", "NothingToConfirm", "TurnContext", "TurnResult"]

log = logging.getLogger(__name__)

SAVED_REPORT_TEXT = "↻ report"  # the hidden message of the follow-up turn after a timeout


class Busy(RuntimeError):
    """The chat cannot take this message now (the reason says why)."""


class NothingToConfirm(RuntimeError):
    """An answer to a question arrived, but no question is open in the chat."""


class ChatRunner:
    """Turns of all chats: one running task per chat, started, resumed, cancelled and continued after a restart."""

    def __init__(self, graph: TurnGraph, ports: Ports, new_budget: BudgetFactory, *, messages: MessageRepo,
                 recursion_limit: int = 60) -> None:  # fmt: skip
        self.ports = ports
        self.messages = messages
        self.journal = TurnJournal(ports.turns, ports.jobs)
        outcomes = OutcomeRecorder(ports, messages)
        replies = TurnReplies(self.journal, messages, outcomes)
        self.execution = TurnExecution(graph, ports, new_budget, self.journal, replies, outcomes, recursion_limit,
                                       report_saved=self._report_saved_later)  # fmt: skip
        self._tasks: dict[str, asyncio.Task[TurnResult]] = {}
        self._follow_up: asyncio.Task[None] | None = None

    async def run_turn(self, chat_id: str, text: str, message_id: str | None = None,
                       preset: dict[str, Any] | None = None) -> TurnResult:  # fmt: skip
        """Handle a message: start a turn, or answer the open question with it. `preset` is a request a button
        already knows (no interpretation call); a panel edit is stored with the hidden role `edit`, so the chat does
        not show it and the interpreter never reads it (spec 007 J, T073)."""
        open_turn = await self._open_turn(chat_id)
        kind = preset_kind(preset)
        entry = route(open_turn.status if open_turn else None, kind)
        if entry in BUSY_REASON:
            raise Busy(BUSY_REASON[entry])
        if entry is Entry.REPLACE_QUESTION and open_turn is not None:
            await self.journal.close_unanswered(open_turn)  # "Change" on a car replaces the open question
        message_id = await self._save_message(chat_id, text, message_id, kind)
        if entry is Entry.ANSWER and open_turn is not None:
            return await self._spawn(open_turn, Command(resume={"choice": "text", "text": text}))
        return await self._start(chat_id, text, message_id, preset)

    async def resume(self, chat_id: str, payload: dict[str, Any]) -> TurnResult:
        """Answer the open question with a button press (run / skip / option:<id> / edit)."""
        open_turn = await self._open_turn(chat_id)
        if open_turn is None or open_turn.status is not TurnStatus.WAITING:
            raise NothingToConfirm("nothing to confirm in this chat")
        return await self._spawn(open_turn, Command(resume=payload))

    async def cancel(self, chat_id: str) -> bool:
        """Stop the chat's turn: the running task is cancelled, a waiting turn closed. False: no open turn."""
        task = self._tasks.get(chat_id)
        if task is not None and not task.done():
            task.cancel()
            return True
        open_turn = await self._open_turn(chat_id)
        if open_turn is None:
            return False
        await self.execution.cancel(open_turn)
        return True

    async def resume_incomplete(self, chat_ids: set[str] | None = None) -> list[str]:
        """After a restart: continue the turns that were RUNNING (not those waiting for the user), FR-044."""
        resumed = []
        for record in await self.ports.turns.running():
            if chat_ids is None or record.chat_id in chat_ids:
                turn = LiveTurn(record.chat_id, record.id, TurnStatus.RUNNING)
                self._tasks[turn.chat_id] = asyncio.create_task(self._execute(turn, None))
                resumed.append(record.id)
        return resumed

    def is_running(self, chat_id: str) -> bool:
        """Does a task of this chat run in this process now?"""
        task = self._tasks.get(chat_id)
        return task is not None and not task.done()

    def task(self, chat_id: str) -> asyncio.Task[TurnResult] | None:
        """The chat's current (or last) turn task in this process."""
        return self._tasks.get(chat_id)

    async def _open_turn(self, chat_id: str) -> LiveTurn | None:
        record: TurnRecord | None = await self.ports.turns.active(chat_id)
        return LiveTurn(chat_id, record.id, TurnStatus(record.status)) if record is not None else None

    async def _save_message(self, chat_id: str, text: str, message_id: str | None, kind: PresetKind | None) -> str:
        """Store the message; the person's words are acknowledged to the client, a panel edit is not."""
        edit = kind in EDITS
        msg = await self.messages.save(chat_id, Role.EDIT if edit else Role.USER, text, message_id=message_id)
        if not edit:
            await self.ports.events.publish(
                chat_id, None, "user_message_ack", {"message_id": msg.id, "created_at": msg.created_at.isoformat()}
            )
        return msg.id

    async def _start(self, chat_id: str, text: str, message_id: str, preset: dict[str, Any] | None) -> TurnResult:
        version, _, _ = await self.ports.cases.latest(chat_id)
        try:
            record = await self.ports.turns.start(chat_id, message_id, version)
        except TurnBusy as e:  # another tab started a turn between the check and this insert
            raise Busy(str(e)) from e
        inputs = {"chat_id": chat_id, "turn_id": record.id, "user_text": text, "preset": preset}
        return await self._spawn(LiveTurn(chat_id, record.id, TurnStatus.RUNNING), inputs)

    async def _spawn(self, turn: LiveTurn, inputs: Any) -> TurnResult:
        task = asyncio.create_task(self._execute(turn, inputs))
        self._tasks[turn.chat_id] = task
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            if task.cancelled():
                return TurnResult(turn.turn_id, TurnStatus.CANCELLED)
            raise

    async def _execute(self, turn: LiveTurn, inputs: Any) -> TurnResult:
        return await self.execution.run(turn, inputs)

    def _report_saved_later(self, chat_id: str, lang: str | None) -> None:
        self._follow_up = asyncio.create_task(self._report_saved(chat_id, lang))

    async def _report_saved(self, chat_id: str, lang: str | None) -> None:
        """A hidden follow-up turn that writes the report from the saved data (never researches again)."""
        preset = {"kind": PresetKind.REPORT_SAVED.value, "language": lang}  # plain data: it enters the graph state
        try:
            await self.run_turn(chat_id, SAVED_REPORT_TEXT, preset=preset)
        except Busy:
            log.info("turn.report_saved_skipped chat=%s (another turn is running)", chat_id)
        except Exception:  # noqa: BLE001 - the timeout message already told the user what to do
            log.exception("turn.report_saved_failed chat=%s", chat_id)
