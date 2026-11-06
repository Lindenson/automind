"""IDENTIFY (spec 005 R1): after the reply is applied, every unsettled or changed car is identified again from its
current facts, in the same turn. Delegates to application.identify; records intake events."""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from automind.chat.application.services.identification import identify
from automind.chat.dialog.nodes.common import ctx, current_year, load_case, notice, record_intake, save_case
from automind.chat.dialog.phrases import market_name, t
from automind.chat.dialog.runner import TurnContext
from automind.chat.dialog.state import TurnState
from automind.chat.domain.case import MAX_CARS

_RANK = {None: 0, "NEED": 1, "NOT_FOUND": 1, "CHOICES": 2, "IDENTIFIED": 3}


async def _notices(c: TurnContext, car: Any, o: Any, url: str | None, lang: str | None) -> list[dict[str, Any]]:
    """What the user should see about this car: a refused link, what was taken from a page, a correction."""
    out = []
    if o.note and o.note.startswith("refused:"):
        out.append(notice(t("page_refused", lang, site=o.note.split(":", 1)[1]), "warning"))
    elif url and car.label and url == car.constraints.url:
        out.append(notice(t("page_taken", lang, what=car.label)))
    name = f"{car.make} {car.model}" if car.make and car.model else car.display_name
    for ev in o.events:  # spec 008: what the ladder did on its own, said (FR-004, FR-005, FR-010, FR-020)
        vals = {k: v for k, v in ev.items() if k != "kind"}
        if "market" in vals:  # a car not sold in Spain: the market named in the user's language
            vals["market"] = market_name(vals["market"], lang)
        out.append(notice(t(ev["kind"], lang, car=name, **vals), "info" if ev["kind"] != "ladder_missing"
                          else "warning"))  # fmt: skip
    if car.previous_label and car.label and car.previous_label != car.label:  # a correction, shown back (FR-014)
        out.append(notice(t("changed_car", lang, before=car.previous_label, after=car.label)))
        await record_intake(c, "CORRECTED", car.key, before=car.previous_label, after=car.label)
    return out


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
        if await identify.drop_wrong_variant(car):
            changes.append(f"{car.key}: {car.previous_label} is not a {car.model} — identified again")
        if not identify.needs_identify(car):
            continue
        ran = True
        await c.status("resolving", f"Identifying {car.display_name}", car=car.display_name)
        url = car.constraints.url
        o = await identify.identify_car(c.ports, case, car, year, lineup_lookup=lookup)
        notices += await _notices(c, car, o, url, state.get("language"))
        if o.outcome != before.get(car.key) or car.label:
            changes.append(f"{car.key}: {o.outcome.lower()}" + (f" → {car.label}" if car.label else ""))
    out: dict[str, Any] = {}
    if ran or changes:
        out["case_version"] = await save_case(c, case, changes, publish=bool(changes))
    # an answer that made the identification better was understood, even with the same make and model (R6)
    improved = {k for k, b in before.items() if _RANK.get(case.car(k).identify.outcome if case.car(k).identify
                                                         else None, 0) > _RANK.get(b, 0)}  # fmt: skip
    delta = (state.get("interpretation") or {}).get("delta") or {}
    touched = {x.get("target_key") for x in [*(delta.get("set_car_context") or []), *(delta.get("replace_cars") or [])]}
    keys = [k for k in state.get("not_understood") or [] if k not in improved and k not in touched]
    out["not_understood"] = keys
    for k in sorted(touched | set(state.get("not_understood") or []) | improved):
        if k and any(x.key == k for x in case.cars):
            await record_intake(c, "ANSWERED", k, progress=k not in keys)
    if notices:
        out["notices"] = [*state.get("notices", []), *notices]
    return out
