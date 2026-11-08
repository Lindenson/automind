"""How a turn ends for the user: the answer (DONE) or the question it waits on (WAITING).

Each writes the turn's row through the journal (the lifecycle checks the step), publishes the events the client
shows (`assistant_message` / `confirm_request`, then `usage`) and records the outcome. The answer is also stored
as a chat message, for replay. Errors: `StoreUnavailable` propagates (the turn fails; it resumes from its
checkpoint).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from automind.chat.application.ports import MessageRepo
from automind.chat.dialog.phrases import t
from automind.chat.dialog.turn.context import TurnContext
from automind.chat.dialog.turn.journal import LiveTurn, TurnJournal
from automind.chat.dialog.turn.outcome import OutcomeRecorder
from automind.chat.domain.turn import Role, TurnStatus


@dataclass
class TurnResult:
    """What a turn ended with, for the caller of the runner (the web layer and the tests)."""

    turn_id: str
    status: TurnStatus
    action: str | None = None
    reply_text: str = ""
    blocks: list[dict[str, Any]] = field(default_factory=list)
    confirm: dict[str, Any] | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    limits_reached: list[str] = field(default_factory=list)
    state: dict[str, Any] = field(default_factory=dict)


class TurnReplies:
    """Ends a turn with its answer or its question."""

    def __init__(self, journal: TurnJournal, messages: MessageRepo, outcomes: OutcomeRecorder) -> None:
        self.journal = journal
        self.messages = messages
        self.outcomes = outcomes

    async def answer(self, ctx: TurnContext, turn: LiveTurn, final: dict[str, Any], started: float) -> TurnResult:
        """DONE: the reply (with a notice of the limits reached) stored, the turn closed, the client told."""
        lang, action = final.get("language"), final.get("action")
        reply = final.get("reply_text") or t("run_no_answer", lang)
        blocks = _with_limits_notice(list(final.get("blocks") or []), ctx.budget.limits_reached, lang)
        msg = await self.messages.save(ctx.chat_id, Role.ASSISTANT, reply, blocks, turn_id=ctx.turn_id)
        usage = ctx.budget.snapshot()
        await self.journal.move(
            turn, TurnStatus.DONE, action=action, fingerprint=final.get("fingerprint"), usage=usage,
            limits_reached=list(ctx.budget.limits_reached), duration_ms=int((time.monotonic() - started) * 1000),
            case_version_after=final.get("case_version"), request_kind=final.get("request_kind"),
        )  # fmt: skip
        await ctx.emit("assistant_message", {
            "message_id": msg.id, "created_at": msg.created_at.isoformat(), "text": reply, "blocks": blocks,
            "action": action, "role": Role.ASSISTANT.value,
            "language": lang,  # spec 004 FR-024: the interface follows the conversation
        })  # fmt: skip
        await ctx.emit("usage", usage)
        await self.outcomes.record(ctx, TurnStatus.DONE, final, started)
        return TurnResult(ctx.turn_id, TurnStatus.DONE, action=action, reply_text=reply, blocks=blocks, usage=usage,
                          limits_reached=list(ctx.budget.limits_reached), state=dict(final))  # fmt: skip

    async def question(self, ctx: TurnContext, turn: LiveTurn, question: object, final: dict[str, Any]) -> TurnResult:
        """WAITING: the graph paused at `question` (an interrupt's value); the next answer resumes it."""
        payload = dict(question) if isinstance(question, dict) else {"text": str(question)}
        await self.journal.move(turn, TurnStatus.WAITING, usage=ctx.budget.snapshot(), action=payload.get("action"))
        await ctx.emit("confirm_request", payload)
        await ctx.emit("usage", ctx.budget.snapshot())
        await self.outcomes.record(ctx, TurnStatus.WAITING, final, time.monotonic())
        return TurnResult(ctx.turn_id, TurnStatus.WAITING, action=payload.get("action"), confirm=payload,
                          usage=ctx.budget.snapshot(), state=final)  # fmt: skip


def _with_limits_notice(blocks: list[dict[str, Any]], limits: list[str], lang: str | None) -> list[dict[str, Any]]:
    if not limits:
        return blocks
    notice = {"type": "notice", "level": "warning", "text": t("run_limits_notice", lang, what=", ".join(limits))}
    return [notice, *blocks]
