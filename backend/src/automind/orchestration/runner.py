"""Per-chat turn runner (research R2, R13, R14; FR-040..FR-044).

One LangGraph thread per chat (`thread_id = chat_id`) on the Postgres checkpointer, so the case
file, pending confirmations and context survive restarts. The runner owns the turn lifecycle:

- one active turn per chat ("busy" otherwise); a message while a confirmation is pending resumes it;
- a `turns` row and a `TurnBudget` per turn (all usage is charged to it);
- graph interrupts become `confirm_request` events and status WAITING_CONFIRMATION;
- the final answer becomes an `assistant_message` + `usage` event, persisted for replay;
- cancel stops the running task and marks the turn CANCELLED.

Graph nodes receive a `TurnContext` through LangGraph's runtime context (no module globals).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from langgraph.types import Command

from automind.application.ports import Ports
from automind.application.usage import BudgetExceeded, TurnBudget, current_budget


@dataclass
class TurnContext:
    """Runtime context passed to every graph node."""

    ports: Ports
    chat_id: str
    turn_id: str
    budget: TurnBudget
    extra: dict[str, Any] = field(default_factory=dict)

    async def emit(self, type_: str, payload: dict[str, Any]) -> int:
        return await self.ports.events.publish(self.chat_id, self.turn_id, type_, payload)

    async def status(self, stage: str, text: str, **extra: Any) -> None:
        await self.emit("status", {"stage": stage, "text": text, **extra})


@dataclass
class TurnResult:
    turn_id: str
    status: str  # DONE | WAITING_CONFIRMATION | CANCELLED | FAILED
    action: str | None = None
    reply_text: str = ""
    blocks: list[dict[str, Any]] = field(default_factory=list)
    confirm: dict[str, Any] | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    limits_reached: list[str] = field(default_factory=list)
    state: dict[str, Any] = field(default_factory=dict)


class Busy(RuntimeError):
    pass


BudgetFactory = Callable[[str, str], TurnBudget]
InputHook = Callable[[str, str, str], Awaitable[dict[str, Any]]]


class ChatRunner:
    def __init__(
        self,
        graph: Any,
        ports: Ports,
        new_budget: BudgetFactory,
        *,
        messages: Any,
        prepare_input: InputHook | None = None,
        thread_per_turn: bool = False,
        recursion_limit: int = 60,
    ) -> None:
        self.graph = graph
        self.ports = ports
        self.new_budget = new_budget
        self.messages = messages
        self.prepare_input = prepare_input
        self.thread_per_turn = thread_per_turn  # legacy demo graph only
        self.recursion_limit = recursion_limit
        self._tasks: dict[str, asyncio.Task[TurnResult]] = {}

    # --- public API ---------------------------------------------------------------------------

    async def run_turn(self, chat_id: str, text: str, message_id: str | None = None) -> TurnResult:
        """Handle a user message: resume a pending confirmation, or start a new turn."""
        active = await self.ports.turns.active(chat_id)
        if active is not None and active.status == "RUNNING":
            raise Busy("a turn is already running in this chat")
        msg = await self.messages.save(chat_id, "user", text, message_id=message_id)
        await self.ports.events.publish(
            chat_id, None, "user_message_ack", {"message_id": msg.id, "created_at": msg.created_at.isoformat()}
        )
        if active is not None and active.status == "WAITING_CONFIRMATION":
            return await self._spawn(chat_id, active.id, Command(resume={"choice": "text", "text": text}))
        version, _, _ = await self.ports.cases.latest(chat_id)
        turn = await self.ports.turns.start(chat_id, msg.id, version)
        inputs: dict[str, Any] = {"chat_id": chat_id, "turn_id": turn.id, "user_text": text}
        if self.prepare_input is not None:
            inputs |= await self.prepare_input(chat_id, turn.id, text)
        return await self._spawn(chat_id, turn.id, inputs)

    async def resume(self, chat_id: str, payload: dict[str, Any]) -> TurnResult:
        """Resume a pending confirmation (button press: run/skip/option:<id>/edit)."""
        active = await self.ports.turns.active(chat_id)
        if active is None or active.status != "WAITING_CONFIRMATION":
            raise RuntimeError("nothing to confirm in this chat")
        return await self._spawn(chat_id, active.id, Command(resume=payload))

    async def cancel(self, chat_id: str) -> bool:
        task = self._tasks.get(chat_id)
        if task is None or task.done():
            active = await self.ports.turns.active(chat_id)
            if active is None:
                return False
            await self._finish_cancelled(chat_id, active.id)  # e.g. waiting for confirmation
            return True
        task.cancel()
        return True

    async def resume_incomplete(self, chat_ids: set[str] | None = None) -> list[str]:
        """After a restart: continue turns that were RUNNING (not waiting for the user), FR-044.

        The graph continues from its last checkpoint (`ainvoke(None)`); research jobs already DONE
        are not run again (nodes/research.py checks the job row).
        """
        resumed = []
        for turn in await self.ports.turns.running():
            if chat_ids is not None and turn.chat_id not in chat_ids:
                continue
            resumed.append(turn.id)
            task = asyncio.create_task(self._execute(turn.chat_id, turn.id, None))
            self._tasks[turn.chat_id] = task
        return resumed

    def is_running(self, chat_id: str) -> bool:
        t = self._tasks.get(chat_id)
        return t is not None and not t.done()

    # --- internals ----------------------------------------------------------------------------

    def _config(self, chat_id: str, turn_id: str) -> dict[str, Any]:
        thread = f"{chat_id}:{turn_id}" if self.thread_per_turn else chat_id
        return {"configurable": {"thread_id": thread}, "recursion_limit": self.recursion_limit}

    async def _spawn(self, chat_id: str, turn_id: str, inputs: Any) -> TurnResult:
        task = asyncio.create_task(self._execute(chat_id, turn_id, inputs))
        self._tasks[chat_id] = task
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            if task.cancelled():
                return TurnResult(turn_id, "CANCELLED")
            raise

    async def _execute(self, chat_id: str, turn_id: str, inputs: Any) -> TurnResult:
        budget = self.new_budget(chat_id, turn_id)
        ctx = TurnContext(self.ports, chat_id, turn_id, budget)
        token = current_budget.set(budget)
        started = time.monotonic()
        await self.ports.turns.update(turn_id, status="RUNNING")
        try:
            async with asyncio.timeout(budget.limits.turn_timeout_s):
                final = await self.graph.ainvoke(inputs, self._config(chat_id, turn_id), context=ctx)
            snapshot = await self.graph.aget_state(self._config(chat_id, turn_id))
            if snapshot.interrupts:
                return await self._waiting(ctx, snapshot.interrupts[0].value, final)
            return await self._done(ctx, final or {}, started)
        except asyncio.CancelledError:
            await self._finish_cancelled(chat_id, turn_id)
            raise
        except BudgetExceeded as e:
            final = {"reply_text": f"I stopped here because a limit was reached: {e}.", "blocks": []}
            return await self._done(ctx, final, started)
        except TimeoutError:
            budget.limits_reached.append("turn_timeout")
            final = {"reply_text": "I stopped because the turn took too long. Ask again to continue.", "blocks": []}
            return await self._done(ctx, final, started)
        except Exception as e:
            await self.ports.turns.update(turn_id, status="FAILED", usage=budget.snapshot())
            await ctx.emit("error", {"text": f"{type(e).__name__}: {e}"[:500]})
            raise
        finally:
            current_budget.reset(token)

    async def _waiting(self, ctx: TurnContext, value: Any, final: Any) -> TurnResult:
        payload = dict(value) if isinstance(value, dict) else {"text": str(value)}
        await self.ports.turns.update(
            ctx.turn_id, status="WAITING_CONFIRMATION", usage=ctx.budget.snapshot(), action=payload.get("action")
        )
        await ctx.emit("confirm_request", payload)
        await ctx.emit("usage", ctx.budget.snapshot())
        return TurnResult(
            ctx.turn_id,
            "WAITING_CONFIRMATION",
            action=payload.get("action"),
            confirm=payload,
            usage=ctx.budget.snapshot(),
            state=dict(final or {}),
        )

    async def _done(self, ctx: TurnContext, final: dict[str, Any], started: float) -> TurnResult:
        reply = final.get("reply_text") or "Sorry, I could not produce an answer."
        blocks = list(final.get("blocks") or [])
        if ctx.budget.limits_reached:
            blocks.insert(
                0,
                {
                    "type": "notice",
                    "level": "warning",
                    "text": "Limit reached this turn: " + ", ".join(ctx.budget.limits_reached),
                },
            )
        action = final.get("action")
        msg = await self.messages.save(ctx.chat_id, "assistant", reply, blocks, turn_id=ctx.turn_id)
        usage = ctx.budget.snapshot()
        await self.ports.turns.update(
            ctx.turn_id,
            status="DONE",
            action=action,
            fingerprint=final.get("fingerprint"),
            usage=usage,
            limits_reached=list(ctx.budget.limits_reached),
            duration_ms=int((time.monotonic() - started) * 1000),
            case_version_after=final.get("case_version"),
            request_kind=final.get("request_kind"),
        )
        await ctx.emit(
            "assistant_message",
            {
                "message_id": msg.id,
                "created_at": msg.created_at.isoformat(),
                "text": reply,
                "blocks": blocks,
                "action": action,
                "role": "assistant",
            },
        )
        await ctx.emit("usage", usage)
        return TurnResult(
            ctx.turn_id,
            "DONE",
            action=action,
            reply_text=reply,
            blocks=blocks,
            usage=usage,
            limits_reached=list(ctx.budget.limits_reached),
            state=dict(final),
        )

    async def _finish_cancelled(self, chat_id: str, turn_id: str) -> None:
        """Validated data already stored stays cached (FR-043); open research jobs are skipped."""
        await self.ports.jobs.skip_open(turn_id)
        await self.ports.turns.update(turn_id, status="CANCELLED")
        await self.ports.events.publish(chat_id, turn_id, "turn_cancelled", {})
