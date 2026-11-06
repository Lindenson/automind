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
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from langgraph.errors import GraphRecursionError
from langgraph.types import Command

from automind.chat.application.ports import Ports, TurnBusy
from automind.chat.dialog import outcomes
from automind.chat.dialog.phrases import t
from automind.chat.dialog.retry import transient_provider_error
from automind.shared.infrastructure.metrics import prom
from automind.shared.metering.usage import BudgetExceeded, TurnBudget, current_budget

log = logging.getLogger(__name__)


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


_PROVIDER_BUSY = ("503", "UNAVAILABLE", "high demand", "overloaded", "RESOURCE_EXHAUSTED", "429",
                  "ProviderUnavailable", "RateLimit", "insufficient_quota")  # fmt: skip


def user_error_text(e: BaseException) -> str:
    """A plain message for the user; technical details stay in the event's `detail` and in the logs."""
    raw = f"{type(e).__name__}: {e}"
    if any(k in raw for k in _PROVIDER_BUSY):
        return ("The AI service is overloaded or out of quota right now. Nothing is lost: send the message "
                "again in a minute. / Сервис ИИ сейчас перегружен или исчерпал квоту. Ничего не потеряно — "
                "отправьте сообщение ещё раз через минуту.")  # fmt: skip
    return "Something went wrong on my side. Please try again. / Что-то пошло не так. Попробуйте ещё раз."


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
        self._follow_up: asyncio.Task[None] | None = None

    # --- public API ---------------------------------------------------------------------------

    async def run_turn(
        self, chat_id: str, text: str, message_id: str | None = None, preset: dict[str, Any] | None = None
    ) -> TurnResult:
        """Handle a user message: resume a pending confirmation, or start a new turn. `preset` is a request a
        button already knows (e.g. "find it": research_more for given cars and areas): no interpretation call.
        A rescore or car-edit preset (a panel edit) is stored with the hidden role `edit`: it is not the user's
        words, so the chat does not show it and the interpreter never reads it (spec 007 J, T073)."""
        active = await self.ports.turns.active(chat_id)
        if active is not None and active.status == "RUNNING":
            raise Busy("a turn is already running in this chat")
        kind = (preset or {}).get("kind")
        edit = kind in ("rescore", "report_saved", "car_edit")
        if kind == "car_edit" and active is not None and active.status == "WAITING_CONFIRMATION":
            await self._supersede(chat_id, active.id)  # "Change" on a car replaces the open question
            active = None
        if edit and active is not None:
            raise Busy("a question is open: the edit is used when the user answers")
        msg = await self.messages.save(chat_id, "edit" if edit else "user", text, message_id=message_id)
        if not edit:
            await self.ports.events.publish(
                chat_id, None, "user_message_ack", {"message_id": msg.id, "created_at": msg.created_at.isoformat()}
            )
        if active is not None and active.status == "WAITING_CONFIRMATION":
            return await self._spawn(chat_id, active.id, Command(resume={"choice": "text", "text": text}))
        version, _, _ = await self.ports.cases.latest(chat_id)
        try:
            turn = await self.ports.turns.start(chat_id, msg.id, version)
        except TurnBusy as e:  # another tab started a turn between the check above and this insert
            raise Busy(str(e)) from e
        inputs: dict[str, Any] = {"chat_id": chat_id, "turn_id": turn.id, "user_text": text, "preset": preset}
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

    async def _language(self, chat_id: str, turn_id: str) -> str | None:
        """The conversation language from the turn state (for the runner's own messages)."""
        try:
            snap = await self.graph.aget_state(self._config(chat_id, turn_id))
            return (snap.values or {}).get("language")
        except Exception:  # noqa: BLE001 - English then
            return None

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

    async def _budget(self, chat_id: str, turn_id: str, inputs: Any) -> Any:
        budget = self.new_budget(chat_id, turn_id)
        if not isinstance(inputs, dict):  # resume (Command) or restart (None): keep usage counted so far
            stored = await self.ports.turns.get(turn_id)
            budget.restore(stored.usage if stored is not None else None)
            snap = await self.graph.aget_state(self._config(chat_id, turn_id))
            budget.extend(int((snap.values or {}).get("limit_extensions") or 0))  # earlier "continue" answers
        spent_today = getattr(self.ports.turns, "spent_today", None)
        if spent_today is not None and budget.limits.daily_cap_eur:  # all chats today, without this turn
            budget.day_spent_eur = await spent_today(exclude_turn=turn_id)
        return budget

    async def _execute(self, chat_id: str, turn_id: str, inputs: Any) -> TurnResult:
        budget = await self._budget(chat_id, turn_id, inputs)
        ctx = TurnContext(self.ports, chat_id, turn_id, budget)
        token = current_budget.set(budget)
        record = outcomes.open_record()  # spec 010 US1: path and signals of this turn
        started = time.monotonic()
        await self.ports.turns.update(turn_id, status="RUNNING")
        try:
            # safety net only: research pauses (and asks) at 85% of the turn time, see TurnBudget.research_pause
            async with asyncio.timeout(budget.limits.turn_timeout_s * 1.5):
                final = await self.graph.ainvoke(inputs, self._config(chat_id, turn_id), context=ctx)
            snapshot = await self.graph.aget_state(self._config(chat_id, turn_id))
            if snapshot.interrupts:
                return await self._waiting(ctx, snapshot.interrupts[0].value, final)
            return await self._done(ctx, final or {}, started)
        except asyncio.CancelledError:
            await self._finish_cancelled(chat_id, turn_id)
            raise
        except BudgetExceeded as e:
            lang = await self._language(chat_id, turn_id)
            final = {"reply_text": t("run_limit", lang, what=str(e)), "blocks": [], "language": lang}
            return await self._done(ctx, final, started)
        except TimeoutError:
            budget.limits_reached.append("turn_timeout")
            lang = await self._language(chat_id, turn_id)
            saved = await self._saved_research(turn_id)
            final = {"reply_text": t("run_timeout_saved" if saved else "run_timeout", lang), "blocks": [],
                     "language": lang}  # fmt: skip
            result = await self._done(ctx, final, started)
            if saved:  # spec 007 FR-029: the report from the data already collected, as a follow-up turn
                self._follow_up = asyncio.create_task(self._report_saved(chat_id, lang))
            return result
        except GraphRecursionError:  # a loop the counters did not stop: a plain answer, never a bare FAILED
            budget.limits_reached.append("graph_steps")
            lang = await self._language(chat_id, turn_id)
            final = {"reply_text": t("run_loop", lang), "blocks": [], "language": lang}
            return await self._done(ctx, final, started)
        except Exception as e:
            if transient_provider_error(e):  # spec 007 FR-028: retried by the node policy; then a plain message
                lang = await self._language(chat_id, turn_id)
                log.warning("turn.provider_unavailable chat=%s turn=%s error=%s", chat_id, turn_id, e)
                final = {"reply_text": t("run_provider_down", lang), "blocks": [], "language": lang,
                         "provider_down": True}  # fmt: skip
                return await self._done(ctx, final, started)
            await self.ports.turns.update(turn_id, status="FAILED", usage=budget.snapshot())
            await self._outcome(ctx, "FAILED", {}, started)
            await ctx.emit("error", {"text": user_error_text(e), "detail": f"{type(e).__name__}: {e}"[:500]})
            raise
        finally:
            outcomes.close_record(record)
            current_budget.reset(token)

    async def _outcome(self, ctx: TurnContext, status: str, final: dict[str, Any], started: float) -> None:
        """Record the turn's outcome and tell the previous turn how its answer landed (spec 010 US1).
        Never fails the turn."""
        store = self.ports.outcomes
        try:
            rec = outcomes.current()
            seconds = time.monotonic() - started
            kind = final.get("request_kind")
            action = final.get("action")
            if store is not None:
                persona = None
                try:
                    _, data, _ = await self.ports.cases.latest(ctx.chat_id)
                    persona = (data or {}).get("persona")
                except Exception:  # noqa: BLE001 - the persona is a cut, not essential
                    persona = None
                signals = {**rec["signals"], **outcomes.final_signals(
                    final, list(ctx.budget.limits_reached), bool(final.get("provider_down")))}  # fmt: skip
                await store.record(
                    ctx.turn_id, ctx.chat_id, request_kind=kind, action=action, status=status,
                    language=final.get("language"), persona=persona, path=rec["path"],
                    duration_ms=int(seconds * 1000), cost_eur=float(ctx.budget.snapshot().get("cost_eur") or 0),
                    signals=signals,
                )  # fmt: skip
                if status != "WAITING_CONFIRMATION":
                    relation, prev = outcomes.previous_signals(final)
                    if relation or prev:
                        await store.patch_previous(ctx.chat_id, ctx.turn_id, relation, prev)
                        await self._feedback_from_relation(ctx, relation, prev)
            if status != "WAITING_CONFIRMATION":
                prom.inc("turns", kind=kind or "unknown", status=status, action=action or "none")
                prom.observe_turn(kind, seconds)
        except Exception:  # noqa: BLE001 - observation must never break a turn
            log.exception("turn.outcome_failed chat=%s turn=%s", ctx.chat_id, ctx.turn_id)

    async def _feedback_from_relation(self, ctx: TurnContext, relation: str | None, prev: dict[str, float]) -> None:
        """A rephrase, a correction or a complaint is feedback too (spec 010 US2)."""
        kind = {"rephrase": "rephrase", "correction": "correction", "complaint": "complaint"}.get(relation or "")
        if kind is None and prev.get("complaint"):
            kind = "complaint"
        if kind is None or self.ports.outcomes is None:
            return
        users = [m for m in await self.messages.history(ctx.chat_id) if getattr(m, "role", "") == "user"]
        text = getattr(users[-1], "text", None) if users else None
        await self.ports.outcomes.feedback(ctx.chat_id, kind, turn_id=ctx.turn_id, text=text)

    async def _saved_research(self, turn_id: str) -> bool:
        """Did this turn store research results before it ran out of time?"""
        try:
            jobs = await self.ports.jobs.for_turn(turn_id)
        except Exception:  # noqa: BLE001 - no job store (demo graph): nothing saved
            return False
        return any(getattr(j, "status", "") == "DONE" for j in jobs)

    async def _report_saved(self, chat_id: str, lang: str | None) -> None:
        """A hidden follow-up turn that writes the report from the saved data (never researches again)."""
        try:
            await self.run_turn(chat_id, "↻ report", preset={"kind": "report_saved", "language": lang})
        except Busy:
            log.info("turn.report_saved_skipped chat=%s (another turn is running)", chat_id)
        except Exception:  # noqa: BLE001 - the timeout message already told the user what to do
            log.exception("turn.report_saved_failed chat=%s", chat_id)

    async def _waiting(self, ctx: TurnContext, value: Any, final: Any) -> TurnResult:
        payload = dict(value) if isinstance(value, dict) else {"text": str(value)}
        await self.ports.turns.update(
            ctx.turn_id, status="WAITING_CONFIRMATION", usage=ctx.budget.snapshot(), action=payload.get("action")
        )
        await ctx.emit("confirm_request", payload)
        await ctx.emit("usage", ctx.budget.snapshot())
        await self._outcome(ctx, "WAITING_CONFIRMATION", dict(final or {}), time.monotonic())
        return TurnResult(
            ctx.turn_id,
            "WAITING_CONFIRMATION",
            action=payload.get("action"),
            confirm=payload,
            usage=ctx.budget.snapshot(),
            state=dict(final or {}),
        )

    async def _done(self, ctx: TurnContext, final: dict[str, Any], started: float) -> TurnResult:
        lang = final.get("language")
        reply = final.get("reply_text") or t("run_no_answer", lang)
        blocks = list(final.get("blocks") or [])
        if ctx.budget.limits_reached:
            blocks.insert(
                0,
                {
                    "type": "notice",
                    "level": "warning",
                    "text": t("run_limits_notice", lang, what=", ".join(ctx.budget.limits_reached)),
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
                "language": final.get("language"),  # spec 004 FR-024: the interface follows the conversation
            },
        )
        await ctx.emit("usage", usage)
        await self._outcome(ctx, "DONE", final, started)
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

    async def _supersede(self, chat_id: str, turn_id: str) -> None:
        """A waiting turn whose question a structured edit replaced: closed without an answer (not a failure)."""
        await self.ports.jobs.skip_open(turn_id)
        await self.ports.turns.update(turn_id, status="CANCELLED")

    async def _finish_cancelled(self, chat_id: str, turn_id: str) -> None:
        """Validated data already stored stays cached (FR-043); open research jobs are skipped."""
        await self.ports.jobs.skip_open(turn_id)
        await self.ports.turns.update(turn_id, status="CANCELLED")
        if self.ports.outcomes is not None:
            try:
                await self.ports.outcomes.record(turn_id, chat_id, status="CANCELLED", signals={"process_failure": 1})
            except Exception:  # noqa: BLE001
                log.exception("turn.outcome_failed chat=%s turn=%s", chat_id, turn_id)
        await self.ports.events.publish(chat_id, turn_id, "turn_cancelled", {})
