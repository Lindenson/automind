"""Whether the message answered the pending question (spec 004 FR-031): car questions left unanswered are asked
again; a yes (or "choose for me") to proposed versions confirms them, a no drops them."""

from __future__ import annotations

from automind.chat.domain.case import CaseFile
from automind.chat.domain.identification import identification


def not_understood(before: CaseFile, after: CaseFile, request: str) -> list[str]:
    """Car keys whose pending question or version proposal the message did not answer (none for a cost question)."""
    p = before.pending
    if p is None or p.kind == "CONFIRM_COST":
        return []
    keys: list[str] = []
    for item in p.items:
        key = str(item.get("car") or "")
        kind = "CONFIRM_VARIANTS" if p.kind == "CONFIRM_VARIANTS" else str(item.get("kind") or "")
        if not key or kind not in (*identification.CAR_QUESTIONS, "CONFIRM_VARIANTS"):
            continue
        b = next((x for x in before.cars if x.key == key), None)
        a = next((x for x in after.cars if x.key == key), None)
        if not identification.answer_settles(kind, b, a, request) and key not in keys:
            keys.append(key)
    return keys


def pending_answered(case: CaseFile, request: str) -> tuple[CaseFile, list[str]]:
    """(a copy of the case with the pending question cleared, the change log). Proposed versions are confirmed by
    confirm_yes / choose_for_me and dropped by confirm_no."""
    if case.pending is None:
        return case, []
    c = case.model_copy(deep=True)
    log: list[str] = []
    proposal = c.pending is not None and c.pending.kind == "CONFIRM_VARIANTS"
    if proposal and request in ("confirm_yes", "choose_for_me"):
        for car in c.cars:
            if car.resolution == "PROPOSED" and car.variant_id:
                car.resolution = "CONFIRMED"
                log.append(f"{car.key} confirmed: {car.label}")
    if proposal and request == "confirm_no":
        for car in c.cars:
            if car.resolution == "PROPOSED":
                car.variant_id, car.label, car.resolution = None, None, "UNRESOLVED"
    c.pending = None
    return c, log
