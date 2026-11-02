"""ASK, CONFIRM_VARIANTS and CONFIRM_COST nodes (FR-005, FR-006, FR-041).

Interrupts re-run their node on resume, so each confirmation is split into
prepare (side effects, once) → wait (only `interrupt`) → apply (record the answer).
"""

from __future__ import annotations

import uuid
from typing import Any

from langgraph.runtime import Runtime
from langgraph.types import interrupt

from automind.application import ask as asking
from automind.application import resolve
from automind.config import settings
from automind.domain.casefile import Pending
from automind.orchestration.phrases import t
from automind.orchestration.runner import TurnContext
from automind.orchestration.state import TurnState

from .common import ctx, current_year, load_case, notice, save_case


async def ask_node(state: TurnState, runtime: Runtime[TurnContext]) -> dict[str, Any]:
    c = ctx(runtime)
    _, case = await load_case(c)
    decision = state["decision"]
    gens = {k: a.get("generations", []) for k, a in state.get("assessments", {}).items()}
    items = asking.fill_questions(decision["questions"], case, c.ports.ref.questions, gens, decision["cars"])
    await c.status("asking", "Asking what I need to know")
    text = await asking.phrase(
        c.ports.llm, c.ports.ref.prompts["asker"], items, state.get("language", "en"), asking.understood_summary(case)
    )
    case = asking.record(case, items)
    version = await save_case(c, case, [f"asked: {', '.join(q['kind'] for q in items)}"])
    return {"reply_text": text, "blocks": [], "action": "ASK", "case_version": version}


# --- variants ------------------------------------------------------------------------------------


def _years(o: dict[str, Any]) -> str:
    lo, hi = o.get("generation_years_from"), o.get("generation_years_to")
    return f" ({lo}–{hi or 'now'})" if lo else ""


async def prepare_variants(state: TurnState, runtime: Runtime[TurnContext]) -> dict[str, Any]:
    """Resolve each car to confirm (catalog first, then the resolver) and propose the best match."""
    c = ctx(runtime)
    _, case = await load_case(c)
    year = current_year(c)
    await c.status("resolving", "Identifying the exact variants")
    options: list[dict[str, Any]] = []
    notices: list[dict[str, Any]] = []
    items: list[dict[str, Any]] = []
    for key in state["decision"]["cars"]:
        car = case.car(key)
        cands = list(state.get("assessments", {}).get(key, {}).get("candidates", []))
        if not cands:
            try:
                v, ident = await resolve.resolve_with_llm(c.ports, car, year)
                cands = [resolve.variant_dict(v)]
                if ident.note:
                    notices.append(notice(f"{v.label}: {ident.note}"))
            except resolve.GenerationMismatch as e:
                notices.append(notice(f"{car.request_text}: {e}. Please tell me the generation or year.", "warning"))
                continue
        best = cands[0]
        car.variant_id, car.label, car.resolution = best["id"], best["label"], "PROPOSED"
        detail = ", ".join(x for x in (car.condition.lower() if car.condition != "UNKNOWN" else "",
                                       f"~{car.year}" if car.year else "") if x)  # fmt: skip
        car_opts = [
            {"id": f"option:{key}:{o['id']}", "label": f"{o['label']}{_years(o)}", "detail": detail or None, "car": key}
            for o in cands[:3]
        ]
        options += car_opts
        items.append({"car": key, "options": car_opts})
        await c.status("resolving", f"{car.request_text} → {best['label']}{_years(best)}", car=best["label"])
    case.pending = Pending(kind="CONFIRM_VARIANTS", items=items)
    await save_case(c, case, [f"{i['car']} proposed: {i['options'][0]['label']}" for i in items])
    lines = [f"- **{i['car']}**: {i['options'][0]['label']}" for i in items]
    text = t("confirm_variants", state.get("language")) + "\n" + "\n".join(lines)
    payload = {
        "kind": "variants",
        "action": "CONFIRM_VARIANTS",
        "request_id": str(uuid.uuid4()),
        "text": text,
        "options": options,
    }
    return {"confirm_payload": payload, "notices": [*state.get("notices", []), *notices]}


def wait_confirm(state: TurnState) -> dict[str, Any]:
    answer = interrupt(state["confirm_payload"])
    return {"resume": answer if isinstance(answer, dict) else {"choice": "text", "text": str(answer)}}


async def apply_variants(state: TurnState, runtime: Runtime[TurnContext]) -> dict[str, Any]:
    """Button choice → confirm; free text → interpret it (it may be a correction, R2)."""
    c = ctx(runtime)
    _, case = await load_case(c)
    answer = state.get("resume") or {}
    choice = str(answer.get("choice") or "")
    if choice in ("text", "edit") or (not choice and answer.get("text")):
        return {"user_text": answer.get("text") or "", "confirm_payload": None, "resume": None, "route": "interpret"}
    if choice == "skip":
        for car in case.cars:
            if car.resolution == "PROPOSED":
                car.variant_id, car.label, car.resolution = None, None, "UNRESOLVED"
        case.pending = None
        await save_case(c, case, ["variant confirmation skipped"])
        return {
            "route": "end",
            "action": "CONFIRM_VARIANTS",
            "reply_text": t("variants_skipped", state.get("language")),
        }
    changes = []
    if choice.startswith("option:"):
        _, key, vid = choice.split(":", 2)
        car = case.car(key)
        v = await resolve.get_variant(vid)
        if v is not None:
            car.variant_id, car.label = v.id, v.label
    for car in case.cars:
        if car.resolution == "PROPOSED" and car.variant_id:
            car.resolution = "CONFIRMED"
            changes.append(f"{car.key} confirmed: {car.label}")
    case.pending = None
    version = await save_case(c, case, changes)
    return {"route": "assess", "confirm_payload": None, "resume": None, "case_version": version}


# --- cost ----------------------------------------------------------------------------------------


async def prepare_cost(state: TurnState, runtime: Runtime[TurnContext]) -> dict[str, Any]:
    c = ctx(runtime)
    _, case = await load_case(c)
    d = state["decision"]
    eur = float(state.get("cost_estimate") or 0)
    await c.status("estimating", f"Estimated research cost €{eur:.2f}")
    lang = state.get("language")
    cap = t("over_cap", lang, cap=f"{settings().cost_hard_cap_eur:.2f}") if d.get("over_cap") else ""
    labels = [case.car(k).label or case.car(k).request_text for k in d["cars"]]
    payload = {
        "kind": "cost",
        "action": "CONFIRM_COST",
        "request_id": str(uuid.uuid4()),
        "text": t("confirm_cost", lang, cars=", ".join(labels), depth=case.depth.lower(), eur=f"{eur:.2f}", cap=cap),
        "options": [],
        "estimate": {"eur": eur, "cars": len(d["cars"]), "areas": _areas(state), "depth": case.depth},
    }
    case.pending = Pending(kind="CONFIRM_COST", items=[{"eur": eur, "cars": d["cars"]}])
    await save_case(c, case, [], publish=False)
    return {"confirm_payload": payload}


async def apply_cost(state: TurnState, runtime: Runtime[TurnContext]) -> dict[str, Any]:
    c = ctx(runtime)
    _, case = await load_case(c)
    answer = state.get("resume") or {}
    choice = str(answer.get("choice") or "")
    case.pending = None
    await save_case(c, case, [], publish=False)
    if choice in ("text", "edit") or (not choice and answer.get("text")):
        return {"user_text": answer.get("text") or "", "confirm_payload": None, "resume": None, "route": "interpret"}
    approved = choice in ("run", "yes", "confirm")
    if not approved:  # remember the refusal for this plan, so the same offer is not repeated every turn
        case.declined_plan = (state.get("research_plan") or {}).get("key")
        await save_case(c, case, ["research declined"], publish=False)
    return {
        "route": "assess",
        "cost_approved": approved,
        "research_declined": not approved,
        "confirm_payload": None,
        "resume": None,
    }


def route_after_apply(state: TurnState) -> str:
    return str(state.get("route") or "assess")


def _areas(state: TurnState) -> list[str]:
    return sorted({a for _, _, a in (state.get("research_plan") or {}).get("jobs", [])})
