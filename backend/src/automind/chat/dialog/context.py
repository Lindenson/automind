"""Helpers shared by graph nodes: context access, case load/save with `case_file` events."""

from __future__ import annotations

from langgraph.runtime import Runtime

from automind.chat.application.services.report.blocks import car_view
from automind.chat.dialog.runner import TurnContext
from automind.chat.domain.case import CaseFile


def ctx(runtime: Runtime[TurnContext]) -> TurnContext:
    assert runtime.context is not None, "graph must run through ChatRunner (TurnContext missing)"
    return runtime.context


def current_year(c: TurnContext) -> int:
    return c.ports.clock.now().year


async def load_case(c: TurnContext) -> tuple[int, CaseFile]:
    version, data, _ = await c.ports.cases.latest(c.chat_id)
    return version, (CaseFile.model_validate(data) if data else CaseFile())


async def save_case(c: TurnContext, case: CaseFile, changes: list[str], *, publish: bool = True) -> int:
    version = await c.ports.cases.save_version(c.chat_id, case.model_dump(mode="json"), "hub", changes)
    if publish:
        await c.emit("case_file", {"version": version, "case": await car_view.case_payload(case), "changes": changes})
    return version


async def history(c: TurnContext, limit: int = 12) -> list[dict[str, str]]:
    msgs = [m for m in await c.ports.messages.history(c.chat_id) if m.role != "edit"]  # panel edits: not words
    prior = msgs[:-1] if msgs and msgs[-1].role == "user" else msgs
    return [{"role": m.role, "text": m.text} for m in prior[-limit:]]


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
