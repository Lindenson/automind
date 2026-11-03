"""IDENTIFY (spec 005 R1): after the reply is applied, every unsettled or changed car is identified again from its
current facts, in the same turn. Delegates to application.identify; records intake events."""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from automind.application import identify
from automind.domain.casefile import MAX_CARS
from automind.orchestration.phrases import t
from automind.orchestration.runner import TurnContext
from automind.orchestration.state import TurnState

from .common import ctx, current_year, load_case, notice, save_case

_RANK = {None: 0, "NEED": 1, "NOT_FOUND": 1, "CHOICES": 2, "IDENTIFIED": 3}


async def identify_node(state: TurnState, runtime: Runtime[TurnContext]) -> dict[str, Any]:
    c = ctx(runtime)
    _, case = await load_case(c)
    year = current_year(c)
    before = {x.key: (x.identify.outcome if x.identify else None) for x in case.cars}
    changes: list[str] = []
    lookup = getattr(c.ports, "lineup", None)
    ran = False
    notices: list[dict[str, Any]] = []
    if len(case.cars) > MAX_CARS:  # which 3 to compare is asked first; nothing is looked up for a 4th car
        return {"not_understood": state.get("not_understood") or []}
    for car in case.cars:
        if not identify.needs_identify(car):
            continue
        ran = True
        await c.status("resolving", f"Identifying {car.display_name}", car=car.display_name)
        url = car.constraints.url
        o = await identify.identify_car(c.ports, case, car, year, lineup_lookup=lookup)
        lang = state.get("language")
        if o.note and o.note.startswith("refused:"):
            notices.append(notice(t("page_refused", lang, site=o.note.split(":", 1)[1]), "warning"))
        elif url and car.label and url == car.constraints.url:
            notices.append(notice(t("page_taken", lang, what=car.label)))
        if car.previous_label and car.label and car.previous_label != car.label:  # a correction, shown back (FR-014)
            notices.append(notice(t("changed_car", lang, before=car.previous_label, after=car.label)))
        if o.outcome != before.get(car.key) or car.label:
            changes.append(f"{car.key}: {o.outcome.lower()}" + (f" → {car.label}" if car.label else ""))
    out: dict[str, Any] = {}
    if ran:
        out["case_version"] = await save_case(c, case, changes, publish=bool(changes))
    # an answer that made the identification better was understood, even with the same make and model (R6)
    improved = {k for k, b in before.items() if _RANK.get(case.car(k).identify.outcome if case.car(k).identify
                                                         else None, 0) > _RANK.get(b, 0)}  # fmt: skip
    delta = (state.get("interpretation") or {}).get("delta") or {}
    touched = {x.get("target_key") for x in [*(delta.get("set_car_context") or []), *(delta.get("replace_cars") or [])]}
    keys = [k for k in state.get("not_understood") or [] if k not in improved and k not in touched]
    out["not_understood"] = keys
    if notices:
        out["notices"] = [*state.get("notices", []), *notices]
    return out
