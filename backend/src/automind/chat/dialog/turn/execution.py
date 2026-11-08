"""One run of the turn graph, from (re)start to its end: answer, question, early ending, cancel or failure.

    run(turn, inputs)
      budget      a new TurnBudget; on a resume or restart it continues the usage counted so far
      RUNNING     the row says the graph works
      graph       ainvoke under the safety-net timeout (research pauses and asks earlier, TurnBudget.research_pause)
      end         a pending interrupt → question (WAITING); else → answer (DONE)
      stopped     an exception with an `Ending` → a plain answer (DONE); cancel → CANCELLED (re-raised);
                  anything else → FAILED, an `error` event, re-raised

`inputs` is the new turn's state (a dict), a `Command(resume=…)` answering the open question, or None to continue a
turn interrupted by a restart from its checkpoint (research jobs already DONE are not run again).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any, Protocol

from langgraph.types import StateSnapshot

from automind.chat.application.ports import Ports, StoreUnavailable
from automind.chat.dialog import tracing
from automind.chat.dialog.phrases import t
from automind.chat.dialog.turn.context import TurnContext
from automind.chat.dialog.turn.endings import Ending, ending_for, user_error_text
from automind.chat.dialog.turn.journal import LiveTurn, TurnJournal
from automind.chat.dialog.turn.outcome import OutcomeRecorder
from automind.chat.dialog.turn.replies import TurnReplies, TurnResult
from automind.chat.domain.turn import OPEN, JobStatus, TurnStatus
from automind.shared.metering.usage import TurnBudget, current_budget

log = logging.getLogger(__name__)

BudgetFactory = Callable[[str, str], TurnBudget]
TIMEOUT_SAFETY = 1.5  # × the turn time: research pauses at 85 % of it, this only catches what did not


class TurnGraph(Protocol):
    """The compiled dialog graph, as the runner uses it (LangGraph's `CompiledStateGraph`)."""

    async def ainvoke(self, input: Any, config: Any = None, *, context: Any = None) -> Any: ...

    async def aget_state(self, config: Any) -> StateSnapshot: ...


class TurnExecution:
    """Runs the graph for one turn and ends the turn whatever happens."""

    def __init__(self, graph: TurnGraph, ports: Ports, new_budget: BudgetFactory, journal: TurnJournal,
                 replies: TurnReplies, outcomes: OutcomeRecorder, recursion_limit: int,
                 report_saved: Callable[[str, str | None], None]) -> None:  # fmt: skip
        self.graph = graph
        self.ports = ports
        self.new_budget = new_budget
        self.journal = journal
        self.replies = replies
        self.outcomes = outcomes
        self.recursion_limit = recursion_limit
        self.report_saved = report_saved  # (chat_id, language): the follow-up report after a timeout

    def config(self, chat_id: str) -> dict[str, Any]:
        """The graph config: one persistent thread per chat."""
        return {"configurable": {"thread_id": chat_id}, "recursion_limit": self.recursion_limit}

    async def run(self, turn: LiveTurn, inputs: Any) -> TurnResult:
        """Run the graph for `turn` and end it (see the module docstring for the endings)."""
        budget = await self._budget(turn, resumed=not isinstance(inputs, dict))
        ctx = TurnContext(self.ports, turn.chat_id, turn.turn_id, budget)
        started = time.monotonic()
        with _turn_scope(budget):
            await self.journal.move(turn, TurnStatus.RUNNING)
            try:
                return await self._graph(ctx, turn, inputs, started)
            except asyncio.CancelledError:
                if turn.status in OPEN:  # a cancel arriving after the answer was written changes nothing
                    await self.cancel(turn)
                raise
            except Exception as e:
                ending = ending_for(e)
                if ending is None:
                    await self._failed(ctx, turn, e, started)
                    raise
                return await self._ended_early(ctx, turn, ending, e, started)

    async def cancel(self, turn: LiveTurn) -> None:
        """CANCELLED: open research jobs skipped, the outcome noted, the client told."""
        await self.journal.close_unanswered(turn)
        await self.outcomes.cancelled(turn.chat_id, turn.turn_id)
        await self.ports.events.publish(turn.chat_id, turn.turn_id, "turn_cancelled", {})

    async def _graph(self, ctx: TurnContext, turn: LiveTurn, inputs: Any, started: float) -> TurnResult:
        async with asyncio.timeout(ctx.budget.limits.turn_timeout_s * TIMEOUT_SAFETY):
            final = await self.graph.ainvoke(inputs, self.config(turn.chat_id), context=ctx)
        snapshot = await self.graph.aget_state(self.config(turn.chat_id))
        if snapshot.interrupts:
            return await self.replies.question(ctx, turn, snapshot.interrupts[0].value, dict(final or {}))
        return await self.replies.answer(ctx, turn, final or {}, started)

    async def _ended_early(self, ctx: TurnContext, turn: LiveTurn, ending: Ending, error: Exception,
                           started: float) -> TurnResult:  # fmt: skip
        if ending.limit:
            ctx.budget.limits_reached.append(ending.limit)
        lang = await self._language(turn.chat_id)
        saved = ending.report_saved and await self._saved_research(turn.turn_id)
        phrase = ending.phrase_when_saved if saved and ending.phrase_when_saved else ending.phrase
        final: dict[str, Any] = {"reply_text": t(phrase, lang, **_what(ending)), "blocks": [], "language": lang}
        if ending.provider_down:
            log.warning("turn.provider_unavailable chat=%s turn=%s error=%s", turn.chat_id, turn.turn_id, error)
            final["provider_down"] = True
        result = await self.replies.answer(ctx, turn, final, started)
        if saved:  # spec 007 FR-029: the report from the data already collected, as a follow-up turn
            self.report_saved(turn.chat_id, lang)
        return result

    async def _failed(self, ctx: TurnContext, turn: LiveTurn, error: Exception, started: float) -> None:
        await self.journal.move(turn, TurnStatus.FAILED, usage=ctx.budget.snapshot())
        await self.outcomes.record(ctx, TurnStatus.FAILED, {}, started)
        await ctx.emit("error", {"text": user_error_text(error), "detail": f"{type(error).__name__}: {error}"[:500]})

    async def _budget(self, turn: LiveTurn, *, resumed: bool) -> TurnBudget:
        """A new budget; a resumed turn keeps the usage counted so far and its earlier "continue" answers."""
        budget = self.new_budget(turn.chat_id, turn.turn_id)
        if resumed:
            stored = await self.ports.turns.get(turn.turn_id)
            budget.restore(stored.usage if stored is not None else None)
            values = (await self.graph.aget_state(self.config(turn.chat_id))).values or {}
            budget.extend(int(values.get("limit_extensions") or 0))
        if budget.limits.daily_cap_eur:  # all chats today, without this turn
            budget.day_spent_eur = await self.ports.turns.spent_today(exclude_turn=turn.turn_id)
        return budget

    async def _language(self, chat_id: str) -> str | None:
        """The conversation language from the graph state (for the runner's own replies); None: English."""
        try:
            snap = await self.graph.aget_state(self.config(chat_id))
        except Exception:  # noqa: BLE001 - English then
            return None
        return (snap.values or {}).get("language")

    async def _saved_research(self, turn_id: str) -> bool:
        """Did this turn store research results before it stopped? (No store: nothing saved.)"""
        try:
            jobs = await self.ports.jobs.for_turn(turn_id)
        except StoreUnavailable:
            return False
        return any(j.status == JobStatus.DONE for j in jobs)


@contextmanager
def _turn_scope(budget: TurnBudget) -> Iterator[None]:
    """The budget all usage is charged to and the outcome record (path, signals) of this run."""
    token = current_budget.set(budget)
    record = tracing.open_record()
    try:
        yield
    finally:
        tracing.close_record(record)
        current_budget.reset(token)


def _what(ending: Ending) -> dict[str, str]:
    return {"what": ending.what} if ending.what is not None else {}
