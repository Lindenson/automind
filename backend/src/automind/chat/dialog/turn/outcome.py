"""What a turn leaves for observation (spec 010 US1/US2): its outcome row, the metrics, and what it says about the
previous answer (a rephrase, a correction or a complaint is feedback on it).

Observation never breaks a turn: a failing store is logged and the turn goes on. Without an outcome store (test
fakes) nothing is recorded but the metrics.
"""

from __future__ import annotations

import logging
import time
from enum import StrEnum
from typing import Any

from automind.chat.application.ports import MessageRepo, OutcomeStore, Ports
from automind.chat.dialog import tracing
from automind.chat.dialog.turn.context import TurnContext
from automind.chat.domain.turn import Role, TurnStatus
from automind.shared.infrastructure.metrics import prom

log = logging.getLogger(__name__)


class FeedbackKind(StrEnum):
    """How this turn relates to the previous answer, when that is feedback on it."""

    REPHRASE = "rephrase"
    CORRECTION = "correction"
    COMPLAINT = "complaint"


class OutcomeRecorder:
    """Records each turn's outcome and the feedback it carries on the previous one."""

    def __init__(self, ports: Ports, messages: MessageRepo) -> None:
        self.ports = ports
        self.messages = messages

    async def record(self, ctx: TurnContext, status: TurnStatus, final: dict[str, Any], started: float) -> None:
        """The outcome of a turn that answered or asked: row, metrics, feedback on the previous answer."""
        try:
            seconds = time.monotonic() - started
            store = self.ports.outcomes
            if store is not None:
                await self._row(store, ctx, status, final, seconds)
                if status is not TurnStatus.WAITING:
                    await self._previous(store, ctx, final)
            if status is not TurnStatus.WAITING:
                prom.inc("turns", kind=final.get("request_kind") or "unknown", status=status,
                         action=final.get("action") or "none")  # fmt: skip
                prom.observe_turn(final.get("request_kind"), seconds)
        except Exception:  # noqa: BLE001 - observation must never break a turn
            log.exception("turn.outcome_failed chat=%s turn=%s", ctx.chat_id, ctx.turn_id)

    async def cancelled(self, chat_id: str, turn_id: str) -> None:
        """A cancelled turn counts as a process failure."""
        if self.ports.outcomes is None:
            return
        try:
            await self.ports.outcomes.record(turn_id, chat_id, status=TurnStatus.CANCELLED,
                                             signals={"process_failure": 1})  # fmt: skip
        except Exception:  # noqa: BLE001 - observation must never break a turn
            log.exception("turn.outcome_failed chat=%s turn=%s", chat_id, turn_id)

    async def _row(self, store: OutcomeStore, ctx: TurnContext, status: TurnStatus, final: dict[str, Any],
                   seconds: float) -> None:  # fmt: skip
        rec = tracing.current()
        signals = {**rec["signals"], **tracing.final_signals(
            final, list(ctx.budget.limits_reached), bool(final.get("provider_down")))}  # fmt: skip
        await store.record(
            ctx.turn_id, ctx.chat_id, request_kind=final.get("request_kind"), action=final.get("action"),
            status=status, language=final.get("language"), persona=await self._persona(ctx.chat_id),
            path=rec["path"], duration_ms=int(seconds * 1000),
            cost_eur=float(ctx.budget.snapshot().get("cost_eur") or 0), signals=signals,
        )  # fmt: skip

    async def _persona(self, chat_id: str) -> Any:
        try:
            _, data, _ = await self.ports.cases.latest(chat_id)
        except Exception:  # noqa: BLE001 - the persona is a cut, not essential
            return None
        return (data or {}).get("persona")

    async def _previous(self, store: OutcomeStore, ctx: TurnContext, final: dict[str, Any]) -> None:
        relation, prev = tracing.previous_signals(final)
        if not (relation or prev):
            return
        await store.patch_previous(ctx.chat_id, ctx.turn_id, relation, prev)
        kind = _feedback_kind(relation, prev)
        if kind is not None:
            await store.feedback(ctx.chat_id, kind, turn_id=ctx.turn_id, text=await self._last_user_text(ctx.chat_id))

    async def _last_user_text(self, chat_id: str) -> str | None:
        users = [m for m in await self.messages.history(chat_id) if m.role == Role.USER]
        return users[-1].text if users else None


def _feedback_kind(relation: str | None, prev: dict[str, float]) -> FeedbackKind | None:
    if relation is not None and relation in FeedbackKind:
        return FeedbackKind(relation)
    return FeedbackKind.COMPLAINT if prev.get("complaint") else None
