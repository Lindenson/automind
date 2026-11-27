"""IDENTIFY (spec 005 R1): after the reply is applied, every unsettled or changed car is identified again from its
current facts, in the same turn (the identification service); the notices and intake events follow."""

from __future__ import annotations

from automind.chat.application.services.identification import IdentificationService
from automind.chat.dialog.context import current_year, load_case, save_case
from automind.chat.dialog.contract import node
from automind.chat.dialog.identification_notes import car_notices, still_not_understood
from automind.chat.dialog.nodes.identify_io import IdentifyIn, IdentifyOut
from automind.chat.dialog.turn.context import TurnContext
from automind.chat.domain.case import MAX_CARS


@node("identify", reads=IdentifyIn, writes=IdentifyOut)
async def identify_node(inp: IdentifyIn, c: TurnContext) -> IdentifyOut:
    """Every unsettled or changed car identified again from its current facts; the notices about each."""
    _, case = await load_case(c)
    if len(case.cars) > MAX_CARS:  # which 3 to compare is asked first; nothing is looked up for a 4th car
        return IdentifyOut(not_understood=inp.not_understood or [])
    service = IdentificationService(c.ports, c.ports.lineup)
    done = await service.identify_case(case, current_year(c), progress=lambda car: c.status(
        "resolving", f"Identifying {car.display_name}", car=car.display_name))  # fmt: skip
    notices = [n for x in done.identified for n in await car_notices(c, x, inp.language)]
    written: dict[str, object] = {}
    if done.identified or done.changes:
        written["case_version"] = await save_case(c, case, done.changes, publish=bool(done.changes))
    delta = (inp.interpretation or {}).get("delta") or {}
    written["not_understood"] = await still_not_understood(c, delta, inp.not_understood or [], case, done.before)
    if notices:
        written["notices"] = [*inp.notices, *notices]
    return IdentifyOut.model_validate(written)
