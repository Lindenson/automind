"""REST API under /api/v1 (contracts/rest-and-mcp.md). Secrets are never returned."""

from __future__ import annotations

import asyncio
import functools
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from automind.config import settings
from automind.domain.casefile import (
    Budget,
    CaseDelta,
    CaseFile,
    Needs,
    PersonaChange,
    Rates,
    RunningLimit,
    apply,
)
from automind.domain.criteria import (
    CriteriaModel,
    reset_weights,
    set_manual_weights,
    weight_breakdown,
    weights_for,
)
from automind.infrastructure import config as cfg
from automind.infrastructure import llm_gateway
from automind.infrastructure.config import search_config

router = APIRouter()


def _msg(m: Any) -> dict[str, Any]:
    return {
        "role": m.role,
        "message_id": m.id,
        "turn_id": m.turn_id,
        "created_at": m.created_at.isoformat(),
        "text": m.text,
        "blocks": m.blocks,
    }


def health_payload(request: Request) -> dict[str, Any]:
    s = settings()
    return {
        "status": "ok",
        "models": llm_gateway.models_by_role(),
        "search": {
            "provider": (sc := search_config()).get("provider"),
            "fallback": sc.get("fallback") or [],
            "keys": {
                "serper": bool(s.serper_api_key),
                "serpapi": bool(s.serpapi_api_key),
                "tavily": bool(s.tavily_api_key),
            },
        },
        "keys": {
            "openai": bool(s.openai_api_key),
            "anthropic": bool(s.anthropic_api_key),
            "gemini": bool(s.google_api_key),
            "tavily": bool(s.tavily_api_key),
        },
        "mcp_tools": [t.name for t in request.app.state.mcp_tools],
    }


@router.get("/api/v1/health")
async def health(request: Request) -> dict[str, Any]:
    return health_payload(request)


@router.get("/api/v1/chats/{chat_id}/messages", response_model=None)
async def messages(chat_id: str, request: Request) -> dict[str, Any] | JSONResponse:
    if await request.app.state.chats.is_deleted(chat_id):
        return _error(410, "chat_deleted", "This chat was deleted.")
    return {"messages": [_msg(m) for m in await request.app.state.messages.history(chat_id)]}


# --- chat deletion (spec 003 US4) -------------------------------------------------------------------


class DeleteChats(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ids: list[str] = Field(min_length=1, max_length=100)


async def _delete(request: Request, ids: list[str]) -> dict[str, Any]:
    from automind.application.chats import delete_chats  # noqa: PLC0415

    st = request.app.state
    deleted, counts = await delete_chats(ids, st.runner, st.chats, st.delete_thread)
    return {"deleted": deleted, "counts": counts}


@router.delete("/api/v1/chats/{chat_id}")
async def delete_chat(chat_id: str, request: Request) -> dict[str, Any]:
    return await _delete(request, [chat_id])


@router.post("/api/v1/chats/delete")
async def delete_many(body: DeleteChats, request: Request) -> dict[str, Any]:
    return await _delete(request, body.ids)


# Demo aliases (kept until the frontend uses v2 everywhere).
@router.get("/api/health")
async def health_alias(request: Request) -> dict[str, Any]:
    return health_payload(request)


@router.get("/api/chats/{chat_id}/messages")
async def messages_alias(chat_id: str, request: Request) -> dict[str, Any]:
    return await messages(chat_id, request)


# --- case file (FR-009) ---------------------------------------------------------------------------


class ProfilePatch(BaseModel):
    """Profile fields the panel edits (spec 007 FR-014); null clears a field."""

    model_config = ConfigDict(extra="forbid")

    family: Literal["SINGLE", "COUPLE", "FAMILY"] | None = None
    driving_style: Literal["CALM", "MIXED", "SPORTY"] | None = None
    age_band: Literal["UNDER_25", "25_40", "40_60", "OVER_60"] | None = None


class CasePatch(BaseModel):
    """User edits from the case panel. Every field is optional. After a report, an edit recomputes it at once
    (spec 007 FR-014); before one, the next turn uses it."""

    model_config = ConfigDict(extra="forbid")

    persona: Literal["EXPERT", "PERFORMANCE", "BUYER", "UNKNOWN"] | None = None
    usage: list[Literal["CITY", "MOTORWAY", "MOUNTAINS", "OFFROAD", "TRACK", "FAMILY"]] | None = None
    budget: Budget | None = None  # partial: only the fields sent change (amount, intent, currency, kind)
    running_cost_limit: RunningLimit | None = None
    clear_running_cost_limit: bool = False
    needs: Needs | None = None  # partial
    annual_km: int | None = None
    rates_override: Rates | None = None
    depth: Literal["QUICK", "STANDARD", "DEEP"] | None = None
    weights: dict[str, float] | None = None  # absolute weights from the sliders; kept as adjustments (spec 007)
    reset_weights: bool = False  # "back to automatic"
    profile: ProfilePatch | None = None  # spec 007: the whole profile is editable in the panel
    ownership_years: int | None = Field(default=None, ge=1, le=20)
    remove_priority: str | None = None


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"code": code, "message": message})


@router.get("/api/v1/chats/{chat_id}/case", response_model=None)
async def get_case(chat_id: str, request: Request) -> dict[str, Any] | JSONResponse:
    if await request.app.state.chats.is_deleted(chat_id):
        return _error(410, "chat_deleted", "This chat was deleted.")
    version, data, changed_by = await request.app.state.cases.latest(chat_id)
    case = CaseFile.model_validate(data) if data else CaseFile()
    return {"version": version, "case": case.model_dump(mode="json"), "changed_by": changed_by}


@router.get("/api/v1/chats/{chat_id}/weights", response_model=None)
async def case_weights(chat_id: str, request: Request) -> dict[str, Any]:
    """The current weights with their reasons (spec 007 FR-011): persona base, profile rules, wishes, the user's
    adjustments. Read by the panel after every case change, so the sliders follow a profile edit at once."""
    version, data, _ = await request.app.state.cases.latest(chat_id)
    case = CaseFile.model_validate(data) if data else CaseFile()
    return {"version": version, **weights_view(case, _criteria_model())}


def weights_view(case: CaseFile, model: CriteriaModel) -> dict[str, Any]:
    b = weight_breakdown(case, model)
    return {
        "weights": {
            k: {"final": round(ln.final, 1), "base": ln.base, "manual": ln.manual,
                "reasons": [{"code": c, "points": p} for c, p in ln.contributions]}
            for k, ln in b.lines.items()
        },
        "manual": b.manual, "capped": list(b.capped), "excluded": list(b.excluded),
    }  # fmt: skip


@router.patch("/api/v1/chats/{chat_id}/case", response_model=None)
async def patch_case(chat_id: str, patch: CasePatch, request: Request) -> dict[str, Any] | JSONResponse:
    st = request.app.state
    active = await st.turns.active(chat_id)
    if active is not None and active.status == "RUNNING":
        return _error(409, "turn_running", "A turn is running; edit the case when it has finished.")
    _, data, _ = await st.cases.latest(chat_id)
    case = CaseFile.model_validate(data) if data else CaseFile()
    try:
        new, changes = apply_patch(case, patch, current_year=datetime.now(UTC).year)
    except (ValueError, ValidationError) as e:
        return _error(422, "invalid_case_edit", str(e))
    if not changes:
        version, _, _ = await st.cases.latest(chat_id)
        return {"version": version, "case": new.model_dump(mode="json"), "changes": []}
    await st.chats.ensure(chat_id)
    version = await st.cases.save_version(chat_id, new.model_dump(mode="json"), "user", changes)
    await st.bus.publish(chat_id, None, "case_file", {"version": version, "case": new.model_dump(mode="json"),
                                                      "changes": changes})  # fmt: skip
    rescore = await _start_rescore(st, chat_id, new, changes)
    return {"version": version, "case": new.model_dump(mode="json"), "changes": changes, "rescore": rescore}


async def _start_rescore(st: Any, chat_id: str, case: CaseFile, changes: list[str]) -> str:
    """Spec 007 FR-014: an edit after a report recomputes it at once from the validated data (no search, no
    interpreter). Before the first report the edit is simply used by the next turn."""
    runner = getattr(st, "runner", None)
    if runner is None or not case.shown or case.pending is not None or not case.cars:
        return "not_needed"
    active = await st.turns.active(chat_id)
    if active is not None:  # a question or a confirmation is open: the edit is used when the user answers
        return "not_needed"
    text = "↻ " + "; ".join(changes)
    preset = {"kind": "rescore", "changes": changes}
    task = asyncio.create_task(runner.run_turn(chat_id, text[:300], None, preset=preset))
    _RESCORES.add(task)
    task.add_done_callback(_RESCORES.discard)
    return "started"


_RESCORES: set[asyncio.Task[Any]] = set()  # keeps the background turns referenced until they finish


def apply_patch(case: CaseFile, patch: CasePatch, *, current_year: int) -> tuple[CaseFile, list[str]]:
    delta = CaseDelta(
        set_persona=PersonaChange(persona=patch.persona, source="USER_EDIT") if patch.persona else None,
        set_usage=patch.usage,
        set_running_cost_limit=patch.running_cost_limit,
        set_needs=patch.needs,
        set_annual_km=patch.annual_km,
        set_depth=patch.depth,
        set_ownership_years=patch.ownership_years,
        remove_priorities=[patch.remove_priority] if patch.remove_priority else [],  # type: ignore[list-item]
    )
    new, changes = apply(case, delta, current_year=current_year)
    if patch.profile is not None:
        changes += _profile_patch(new, patch.profile)
    if patch.budget is not None:  # a panel edit sets exactly what was sent (also clearing the amount)
        budget = new.budget.model_copy(update=patch.budget.model_dump(exclude_unset=True))
        if budget != new.budget:
            new.budget = budget
            changes.append(f"budget: {budget.max_eur or 'none'} {budget.currency}, {budget.intent.lower()}")
    if patch.clear_running_cost_limit and new.running_cost_limit is not None:
        new.running_cost_limit = None
        changes.append("running cost limit removed")
    if patch.rates_override is not None:  # explicit nulls clear an override (back to the default rate)
        rates = new.rates_override.model_copy(update=patch.rates_override.model_dump(exclude_unset=True))
        if rates != new.rates_override:
            new.rates_override = rates
            changes.append(
                "rates: "
                + (", ".join(f"{k}={v}" for k, v in rates.model_dump(exclude_none=True).items()) or "defaults")
            )
    if patch.reset_weights:
        new = reset_weights(new)
        changes.append("weights: automatic")
    if patch.weights is not None:
        model = _criteria_model()
        new = set_manual_weights(new, patch.weights, model)
        changes.append("weights: " + ", ".join(f"{k} {v:.0f}%" for k, v in weights_for(new, model).items() if v))
    return new, changes


def _profile_patch(case: CaseFile, p: ProfilePatch) -> list[str]:
    """Set exactly what was sent (a panel edit is a statement: STATED); null clears the field."""
    out = []
    for f in p.model_fields_set:
        val = getattr(p, f)
        if getattr(case.profile, f) == val:
            continue
        setattr(case.profile, f, val)
        if val is None:
            case.profile.evidence.pop(f, None)
            case.basis.pop(f, None)
        else:
            case.profile.evidence[f] = "set in the panel"
            case.basis[f] = "STATED"
        out.append(f"{f.replace('_', ' ')}: {(val or 'not set').lower()}")
    return out


@functools.cache
def _criteria_model() -> CriteriaModel:
    return CriteriaModel.from_config(cfg.load_yaml("criteria.yaml"), cfg.load_yaml("profile_rules.yaml"))


@router.get("/api/v1/research/metrics")
async def research_metrics(days: int = 7) -> dict[str, Any]:
    """Research quality for the operator (spec 003 FR-017, FR-031): minimums met, rejections by reason,
    site reader success, search cost and cache hits."""
    from automind.infrastructure.db.repositories import MetricsRepo  # noqa: PLC0415

    return await MetricsRepo().research(max(1, min(days, 365)))


@router.get("/api/v1/criteria")
async def criteria() -> dict[str, Any]:
    """The criteria dictionary (labels, definitions, persona default weights)."""
    d = cfg.load_yaml("criteria.yaml")
    return {
        "version": d["criteria_version"],
        "personas": d["personas"],
        "criteria": [{"key": k, "label": v["label"], "definition": v["definition"]} for k, v in d["criteria"].items()],
    }


@router.get("/api/v1/chats")
async def chats(request: Request) -> dict[str, Any]:
    """Past chats, newest first, with the cars and persona of their case file (FR-045)."""
    st = request.app.state
    out = []
    for ch in await st.chats.list():
        _, data, _ = await st.cases.latest(ch.id)
        case = CaseFile.model_validate(data) if data else CaseFile()
        out.append(
            {
                "id": ch.id,
                "title": ch.title,
                "updated_at": ch.updated_at.isoformat(),
                "cars": [c.label or c.request_text for c in case.cars],
                "persona": case.persona,
            }
        )
    return {"chats": out}
