"""IDENTIFY (spec 005 R1): after the reply is applied, every unsettled or changed car is identified again from its
current facts, in the same turn (the identification service); the notices and intake events follow."""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from automind.chat.application.services.identification import IdentificationService
from automind.chat.dialog.context import ctx, current_year, load_case, save_case
from automind.chat.dialog.identification_notes import car_notices, still_not_understood
from automind.chat.dialog.state import TurnState
from automind.chat.dialog.turn.context import TurnContext
from automind.chat.domain.case import MAX_CARS


async def identify_node(state: TurnState, runtime: Runtime[TurnContext]) -> dict[str, Any]:
    c = ctx(runtime)
    _, case = await load_case(c)
    if len(case.cars) > MAX_CARS:  # which 3 to compare is asked first; nothing is looked up for a 4th car
        return {"not_understood": state.get("not_understood") or []}
    service = IdentificationService(c.ports, c.ports.lineup)
    done = await service.identify_case(case, current_year(c), progress=lambda car: c.status(
        "resolving", f"Identifying {car.display_name}", car=car.display_name))  # fmt: skip
    notices = [n for x in done.identified for n in await car_notices(c, x, state.get("language"))]
    out: dict[str, Any] = {}
    if done.identified or done.changes:
        out["case_version"] = await save_case(c, case, done.changes, publish=bool(done.changes))
    out["not_understood"] = await still_not_understood(c, state, case, done.before)
    if notices:
        out["notices"] = [*state.get("notices", []), *notices]
    return out
