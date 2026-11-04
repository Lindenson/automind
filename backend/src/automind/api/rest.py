"""REST API under /api/v1 (contracts/rest-and-mcp.md). Secrets are never returned."""

from __future__ import annotations

import asyncio
import functools
import logging
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from automind.application.ports import TurnBusy, VersionConflict
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
from automind.orchestration.runner import Busy

router = APIRouter()
log = logging.getLogger(__name__)


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
    msgs = await request.app.state.messages.history(chat_id)
    return {"messages": [_msg(m) for m in msgs if m.role != "edit"]}  # panel edits are not chat messages


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
    home_charging: Literal["YES", "WORK", "NO"] | None = None  # spec 006: null = not known


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
    if_version: int | None = None  # the version the edit was made on (optimistic lock, spec 007 J)


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
    """A panel edit (spec 007 FR-014, J). It is saved under the turn-start lock with a version check, so a turn
    never overwrites it and two edits never lose each other. While a turn runs it is queued and applied right
    after that turn (no 409 for a slider move). After a report it starts (or joins) the chat's rescore."""
    st = request.app.state
    await st.chats.ensure(chat_id)
    version, data, _ = await st.cases.latest(chat_id)
    if patch.if_version is not None and patch.if_version != version:
        case = CaseFile.model_validate(data) if data else CaseFile()
        body = {"code": "version_conflict", "message": "The case changed.", "version": version,
                "case": case.model_dump(mode="json")}  # fmt: skip
        return JSONResponse(status_code=409, content=body)
    try:
        saved = await save_patch(st, chat_id, patch)
    except (ValueError, ValidationError) as e:
        return _error(422, "invalid_case_edit", str(e))
    if saved is None:  # a turn is running: applied after it
        _QUEUED.setdefault(chat_id, []).append(patch)
        _kick(st, chat_id)
        version, data, _ = await st.cases.latest(chat_id)
        return {"version": version, "case": data or {}, "changes": [], "rescore": "queued", "queued": True}
    version, new, changes = saved
    if changes:
        await st.bus.publish(chat_id, None, "case_file", {"version": version, "case": new.model_dump(mode="json"),
                                                          "changes": changes})  # fmt: skip
    rescore = _want_rescore(st, chat_id, new, changes)
    return {"version": version, "case": new.model_dump(mode="json"), "changes": changes, "rescore": rescore}


async def save_patch(st: Any, chat_id: str, patch: CasePatch) -> tuple[int, CaseFile, list[str]] | None:
    """Apply the edit on the newest case and save it; None while a turn runs. A concurrent writer (another edit)
    makes it re-read and apply again."""
    for _ in range(5):
        version, data, _ = await st.cases.latest(chat_id)
        case = CaseFile.model_validate(data) if data else CaseFile()
        new, changes = apply_patch(case, patch, current_year=datetime.now(UTC).year)
        if not changes:
            return version, new, []
        try:
            v = await st.cases.save_if_idle(chat_id, new.model_dump(mode="json"), "user", changes,
                                            expected_version=version)  # fmt: skip
        except TurnBusy:
            return None
        except VersionConflict:
            continue
        return v, new, changes
    raise ValueError("the case keeps changing; try again")


# --- the rescore queue (spec 007 J, T074/T075) -----------------------------------------------------------------
# One worker per chat. Edits made while a turn runs wait in _QUEUED and are applied when it ends; the changes of
# all edits since the last rescore are merged in _CHANGES and recomputed once. A rescore that meets a busy chat
# is retried after the turn; any other failure is logged and told to the chat (`rescore_failed`), never dropped.

_QUEUED: dict[str, list[CasePatch]] = {}
_CHANGES: dict[str, list[str]] = {}
_WORKERS: dict[str, asyncio.Task[Any]] = {}
RESCORE_POLL_S = 0.3
RESCORE_WAIT_S = 900.0  # longest wait for a running turn (a research turn can take minutes)


def _want_rescore(st: Any, chat_id: str, case: CaseFile, changes: list[str]) -> str:
    if getattr(st, "runner", None) is None or not changes or not case.shown or not case.cars:
        return "not_needed"
    if case.pending is not None:  # a question is open: the edit is used when the user answers
        return "not_needed"
    _CHANGES.setdefault(chat_id, []).extend(changes)
    return "queued" if _kick(st, chat_id) == "joined" else "started"


def _kick(st: Any, chat_id: str) -> str:
    task = _WORKERS.get(chat_id)
    if task is not None and not task.done():
        return "joined"
    _WORKERS[chat_id] = asyncio.create_task(_rescore_worker(st, chat_id))
    return "started"


async def _idle(st: Any, chat_id: str) -> str:
    """Wait for the running turn to end: 'idle', 'waiting' (a question is open) or 'timeout'."""
    waited = 0.0
    while waited < RESCORE_WAIT_S:
        active = await st.turns.active(chat_id)
        if active is None:
            return "idle"
        if active.status != "RUNNING":
            return "waiting"
        await asyncio.sleep(RESCORE_POLL_S)
        waited += RESCORE_POLL_S
    return "timeout"


async def _apply_queued(st: Any, chat_id: str) -> bool:
    """Apply the edits queued during a turn; False when a turn started again in between."""
    queued = _QUEUED.pop(chat_id, [])
    for i, patch in enumerate(queued):
        saved = await save_patch(st, chat_id, patch)
        if saved is None:
            _QUEUED[chat_id] = queued[i:] + _QUEUED.get(chat_id, [])
            return False
        version, new, changes = saved
        if changes:
            await st.bus.publish(chat_id, None, "case_file", {"version": version, "case": new.model_dump(mode="json"),
                                                              "changes": changes})  # fmt: skip
            _CHANGES.setdefault(chat_id, []).extend(changes)
    return True


async def _rescore_worker(st: Any, chat_id: str) -> None:
    try:
        while _QUEUED.get(chat_id) or _CHANGES.get(chat_id):
            state = await _idle(st, chat_id)
            if state == "timeout":
                await _rescore_failed(st, chat_id, "the running turn did not finish")
                return
            if not await _apply_queued(st, chat_id):
                continue
            changes = _CHANGES.pop(chat_id, [])
            if not changes:
                continue
            _, data, _ = await st.cases.latest(chat_id)
            case = CaseFile.model_validate(data) if data else CaseFile()
            if state == "waiting" or case.pending is not None or not case.shown or not case.cars:
                continue  # the edit is in the case: the answer to the open question uses it
            try:
                await st.runner.run_turn(chat_id, ("↻ " + "; ".join(changes))[:300], None,
                                         preset={"kind": "rescore", "changes": changes})  # fmt: skip
            except Busy:
                _CHANGES[chat_id] = changes + _CHANGES.get(chat_id, [])  # a turn won the race: after it
    except Exception as e:  # noqa: BLE001 - never lose an edit silently
        log.exception("rescore failed", extra={"chat_id": chat_id})
        await _rescore_failed(st, chat_id, type(e).__name__)
    finally:
        _WORKERS.pop(chat_id, None)


async def _rescore_failed(st: Any, chat_id: str, why: str) -> None:
    _CHANGES.pop(chat_id, None)
    try:
        await st.bus.publish(chat_id, None, "rescore_failed", {"reason": why})
    except Exception:  # noqa: BLE001
        log.exception("could not report a failed rescore")


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
        if f == "home_charging" and val is None:
            val = "UNKNOWN"
        if getattr(case.profile, f) == val:
            continue
        setattr(case.profile, f, val)
        if val in (None, "UNKNOWN"):
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
