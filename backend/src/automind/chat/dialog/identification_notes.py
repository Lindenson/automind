"""What the chat says and records after the identify step (spec 005 R6, R10, R13; spec 008): the notices about each
identified car in the person's language (a refused link, what was taken from a page, what the ladder did on its
own, a correction), and which of the person's answers are understood now."""

from __future__ import annotations

from automind.chat.application.services.identification.service import CarIdentified
from automind.chat.application.services.report.blocks.notice import Notice, notice
from automind.chat.dialog.context import record_intake
from automind.chat.dialog.phrases import market_name, t
from automind.chat.dialog.state import TurnState
from automind.chat.dialog.turn.context import TurnContext
from automind.chat.domain.case import CaseFile

_RANK = {None: 0, "NEED": 1, "NOT_FOUND": 1, "CHOICES": 2, "IDENTIFIED": 3}  # how far an outcome got


async def car_notices(c: TurnContext, done: CarIdentified, lang: str | None) -> list[Notice]:
    """What the user should see about this car: a refused link, what was taken from a page, a correction."""
    car, o, url = done.car, done.outcome, done.page_url
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


async def still_not_understood(c: TurnContext, state: TurnState, case: CaseFile,
                               before: dict[str, str | None]) -> list[str]:  # fmt: skip
    """The cars whose answer is still not understood. An answer that made the identification better was understood,
    even with the same make and model (R6); every car the answer touched is recorded as answered."""
    improved = {k for k, b in before.items() if _RANK.get(case.car(k).identify.outcome if case.car(k).identify
                                                         else None, 0) > _RANK.get(b, 0)}  # fmt: skip
    delta = (state.get("interpretation") or {}).get("delta") or {}
    touched = {x.get("target_key") for x in [*(delta.get("set_car_context") or []), *(delta.get("replace_cars") or [])]}
    keys = [k for k in state.get("not_understood") or [] if k not in improved and k not in touched]
    for k in sorted(touched | set(state.get("not_understood") or []) | improved):
        if k and any(x.key == k for x in case.cars):
            await record_intake(c, "ANSWERED", k, progress=k not in keys)
    return keys
