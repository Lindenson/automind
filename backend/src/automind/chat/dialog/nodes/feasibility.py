"""Feasibility verdict before the report (spec 003 US3; FR-019..FR-021, research R12).

prepare_feasibility → wait (interrupt: report | used | alternatives | text) → apply_feasibility.
The verdict and its numbers come from application.feasibility (code); this node only asks.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from langgraph.runtime import Runtime

from automind.chat.application.services.feasibility import feasibility as fz_app
from automind.chat.dialog.context import ctx, load_case, save_case
from automind.chat.dialog.phrases import t
from automind.chat.dialog.runner import TurnContext
from automind.chat.dialog.state import TurnState
from automind.chat.domain.case import CaseFile


def needs_ack(case: CaseFile) -> str:
    """Acknowledgement that covers the current constraints whatever the data shows later ("look at used")."""
    payload = json.dumps(fz_app.constraint_lines(case) + [case.budget.intent], sort_keys=True)
    return "needs:" + hashlib.sha256(payload.encode()).hexdigest()[:24]


def pending(case: CaseFile, data: dict[str, Any] | None) -> bool:
    fp = (data or {}).get("fingerprint")
    return bool(fp) and case.feasibility_ack not in (fp, needs_ack(case))


async def prepare_feasibility(state: TurnState, runtime: Runtime[TurnContext]) -> dict[str, Any]:
    c = ctx(runtime)
    _, case = await load_case(c)
    data = state.get("feasibility") or {}
    await fz_app.persist(c.ports.feasibility, c.chat_id, c.turn_id, case, data)
    lang = state.get("language")
    lines = "\n".join(f"- {x}" for x in fz_app.problems(data))
    options = [{"id": "report", "label": t("feasibility_report", lang)}]
    budget_problem = any(
        ch["check"] == "BUDGET" and ch["verdict"] in ("DOES_NOT_FIT", "USED_ONLY")
        for r in data.get("results", []) for ch in r["checks"]
    )  # fmt: skip
    if budget_problem and case.budget.intent != "USED":
        options.append({"id": "used", "label": t("feasibility_used", lang)})
    options.append({"id": "alternatives", "label": t("feasibility_alternatives", lang)})
    text = f"{t('feasibility_intro', lang)}\n{lines}\n\n{t('feasibility_question', lang)}"
    await c.status("feasibility", "Checking the request against your budget and needs")
    payload = {"kind": "feasibility", "action": "FEASIBILITY", "request_id": str(uuid.uuid4()), "text": text,
               "options": options}  # fmt: skip
    return {"confirm_payload": payload, "action": "FEASIBILITY"}


async def apply_feasibility(state: TurnState, runtime: Runtime[TurnContext]) -> dict[str, Any]:
    c = ctx(runtime)
    _, case = await load_case(c)
    answer = state.get("resume") or {}
    choice = str(answer.get("choice") or "")
    data = state.get("feasibility") or {}
    if choice in ("text", "edit") or (not choice and answer.get("text")):
        return {"user_text": answer.get("text") or "", "confirm_payload": None, "resume": None, "route": "interpret"}
    if choice == "used":
        case.budget = case.budget.model_copy(update={"intent": "USED"})
        over = {
            r["car_key"] for r in data.get("results", [])
            for ch in r["checks"] if ch["check"] == "BUDGET" and ch["verdict"] != "FITS"
        }  # fmt: skip
        for car in case.cars:
            if car.key in over or car.condition == "UNKNOWN":
                car.condition = "USED"
        case.feasibility_ack = needs_ack(case)
        await save_case(c, case, ["looking at used cars for the budget"])
        return {"route": "assess", "confirm_payload": None, "resume": None}
    case.feasibility_ack = data.get("fingerprint")
    await save_case(c, case, ["feasibility answered: " + (choice or "report")], publish=False)
    if choice == "alternatives":
        return {"route": "alternatives", "confirm_payload": None, "resume": None}
    return {"route": "assess", "confirm_payload": None, "resume": None}


async def alternatives(state: TurnState, runtime: Runtime[TurnContext]) -> dict[str, Any]:
    """Suggest kinds of cars that would fit (labelled as suggestions; no numbers without validated data)."""
    c = ctx(runtime)
    _, case = await load_case(c)
    data = state.get("feasibility") or {}
    lang = state.get("language") or "en"
    user = (
        f"Language: {lang}\nUser's constraints: {'; '.join(fz_app.constraint_lines(case))}\n"
        f"Cars considered and why they do not fit:\n" + "\n".join(f"- {x}" for x in fz_app.problems(data)) +
        "\n\nSuggest 2–4 kinds of cars (class, body, powertrain, typical models) that would fit these constraints. "
        "Do not state prices or specifications as facts; say they are suggestions to research next."
    )  # fmt: skip
    system = c.ports.ref.prompts.get("general", "").format(language=lang)
    text = await c.ports.llm.text("general", system, user)
    return {"reply_text": text.strip(), "blocks": [b for b in [fz_app.block(case, data)] if b], "action": "FEASIBILITY"}


def route_after_apply(state: TurnState) -> str:
    return str(state.get("route") or "assess")
