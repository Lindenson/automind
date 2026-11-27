"""Helpers shared by graph nodes: context access, the conversation history, intake events. The case file is the
context's own (`TurnContext.case()` / `save_case`, spec 014 D3)."""

from __future__ import annotations

from langgraph.runtime import Runtime

from automind.chat.application.ports import IntakeLog
from automind.chat.dialog.turn.context import TurnContext
from automind.chat.domain.turn import Role


def ctx(runtime: Runtime[TurnContext]) -> TurnContext:
    assert runtime.context is not None, "graph must run through ChatRunner (TurnContext missing)"
    return runtime.context


def current_year(c: TurnContext) -> int:
    return c.ports.clock.now().year


async def history(c: TurnContext, limit: int = 12) -> list[dict[str, str]]:
    msgs = [m for m in await c.ports.messages.history(c.chat_id) if m.role != Role.EDIT]  # panel edits: not words
    prior = msgs[:-1] if msgs and msgs[-1].role == Role.USER else msgs
    return [{"role": m.role, "text": m.text} for m in prior[-limit:]]


def intake_log(c: TurnContext) -> IntakeLog:
    """The turn's intake log as the services' port (`record_intake` of this turn)."""

    async def log(kind: str, car_key: str | None = None, item: str | None = None, **details: object) -> None:
        await record_intake(c, kind, car_key, item, **details)

    return log


async def record_intake(c: TurnContext, kind: str, car_key: str | None = None, item: str | None = None,
                        **details: object) -> None:  # fmt: skip
    """One intake event (spec 005 R13); never fails the turn."""
    from automind.shared.infrastructure import db  # noqa: PLC0415

    try:
        async with db.sessionmaker()() as s:
            if await s.get(db.Chat, c.chat_id) is None:
                return
            s.add(db.IntakeEvent(chat_id=c.chat_id, turn_id=c.turn_id, car_key=car_key, kind=kind, item=item,
                                 details=dict(details)))  # fmt: skip
            await s.commit()
    except Exception:  # noqa: BLE001 - metrics only
        return
