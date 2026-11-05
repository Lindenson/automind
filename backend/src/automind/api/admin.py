"""Admin API (spec 010 US4, contracts/admin-api.md): Top problems and Sources; spec 011 US6 adds Parsers, Changes,
the accuracy drill-down and the engine status strip, read through `automind.acquisition.admin_api`.

Every route requires the admin token (or this machine when none is set). Detailed metrics and alerts are in
Prometheus, not here (FR-029).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from automind.acquisition import admin_api
from automind.acquisition.registry.domain.model import ACCESS_BLOCKING
from automind.acquisition.registry.domain.seed_rules import denied
from automind.api import access
from automind.config import settings
from automind.infrastructure.config import load_yaml
from automind.infrastructure.db.models import (
    CapabilityRow,
    InsightIssue,
    RegistryChange,
    SourceRow,
    TruthSignal,
    now,
)
from automind.infrastructure.db.session import sessionmaker
from automind.insight.domain.issue_text import copy_text
from automind.insight.metrics import prom

router = APIRouter(prefix="/api/v1/admin")


def require_admin(request: Request) -> None:
    client = request.client.host if request.client else None
    if not access.admin_ok(request.headers.get("authorization"), client, settings().admin_token):
        raise HTTPException(status_code=403, detail="forbidden")


Admin = Depends(require_admin)


def _row(i: InsightIssue) -> dict[str, Any]:
    return {c.name: getattr(i, c.name) for c in InsightIssue.__table__.columns}


def _fix(i: InsightIssue) -> dict[str, Any] | None:
    return (i.diagnosis or {}).get("fix") if i.diagnosis else None


def _example_chat(i: InsightIssue) -> str | None:
    return next((e.get("chat_id") for e in i.examples or [] if e.get("chat_id")), None)


@router.get("/problems", dependencies=[Admin])
async def problems() -> list[dict[str, Any]]:
    """The 10 open or regression issues with the highest impact (FR-026)."""
    n = int(load_yaml("insight.yaml").get("top", 10))
    async with sessionmaker()() as s:
        q = (
            select(InsightIssue)
            .where(InsightIssue.status.in_(("open", "acknowledged", "regression")))
            .order_by(InsightIssue.impact.desc(), InsightIssue.last_seen.desc())
            .limit(n)
        )
        rows = list((await s.execute(q)).scalars())
    return [
        {
            "id": i.id,
            "rank": k,
            "title": i.title,
            "component": i.component,
            "status": i.status,
            "impact": round(i.impact, 2),
            "failing_turns_7d": i.count_7d,
            "chats_7d": i.chats_7d,
            "example_chat": _example_chat(i),
            "fix": _fix(i),
            "source": i.source,
        }
        for k, i in enumerate(rows, 1)
    ]


@router.get("/problems/{issue_id}", dependencies=[Admin])
async def problem(issue_id: str) -> dict[str, Any]:
    async with sessionmaker()() as s:
        i = await s.get(InsightIssue, issue_id)
        if i is None:
            raise HTTPException(status_code=404, detail="not found")
        row = _row(i)
    return {**row, "copy_text": copy_text(row)}


class StatusIn(BaseModel):
    status: Literal["open", "acknowledged", "fixed", "wontfix"]
    fixed_ref: str | None = Field(default=None, max_length=80)


@router.patch("/problems/{issue_id}", dependencies=[Admin])
async def set_status(issue_id: str, body: StatusIn) -> dict[str, Any]:
    async with sessionmaker()() as s:
        i = await s.get(InsightIssue, issue_id)
        if i is None:
            raise HTTPException(status_code=404, detail="not found")
        t = now()
        i.status = body.status
        if body.status == "fixed":
            i.fixed_at, i.fixed_ref = t, body.fixed_ref or i.fixed_ref
        i.status_history = [
            *(i.status_history or []),
            {"at": t.isoformat(), "status": body.status, "by": "owner", "ref": body.fixed_ref},
        ]
        await s.commit()
        row = _row(i)
    return {**row, "copy_text": copy_text(row)}


# --- Sources (spec 010 US7, FR-028) ------------------------------------------------------------------------------

USABLE = ("active", "candidate", "degraded")


def _cap_out(c: CapabilityRow, rank: int | None, src: SourceRow | None) -> dict[str, Any]:
    return {
        "capability_id": c.id,
        "domain": c.domain,
        "area": c.area,
        "market": c.market,
        "status": c.status,
        "rank": rank,
        "score": round(c.score, 4),
        "acc_mean": round(c.acc_mean, 4),
        "acc_lb": round(c.acc_lb, 4),
        "yield": round(c.yield_, 4),
        "attempts": round(c.attempts, 1),
        "accepted": round(c.accepted, 1),
        "wrong_w": round(c.wrong_w, 2),
        "right_w": round(c.right_w, 2),
        "cost_per_value": round(c.cost_eur / c.accepted, 4) if c.accepted else None,
        "frozen": bool(src and src.frozen),
        "access": src.access if src else "unknown",
        "source_type": src.source_type if src else None,
        "last_used": c.last_used,
    }


def _change_out(ch: RegistryChange) -> dict[str, Any]:
    return {
        "id": ch.id,
        "at": ch.created_at,
        "author": ch.author,
        "domain": ch.domain,
        "area": (ch.after or {}).get("area") or (ch.evidence or {}).get("area"),
        "market": (ch.after or {}).get("market") or (ch.evidence or {}).get("market"),
        "change": ch.change,
        "before": ch.before,
        "after": ch.after,
        "reason": ch.reason,
        "evidence": ch.evidence,
        "held": ch.held,
        "reverted": ch.reverted_by is not None,
        "revertible": not ch.held and ch.reverted_by is None and ch.change not in ("added", "reverted"),
        "capability_id": ch.capability_id,
    }


@router.get("/sources", dependencies=[Admin])
async def sources(area: str = "specs") -> dict[str, Any]:
    async with sessionmaker()() as s:
        caps = list((await s.execute(select(CapabilityRow).where(CapabilityRow.area == area))).scalars())
        srcs = {
            r.domain: r
            for r in (
                await s.execute(select(SourceRow).where(SourceRow.domain.in_({c.domain for c in caps})))
            ).scalars()
        }
    usable = sorted((c for c in caps if c.status in USABLE), key=lambda c: (c.status != "active", -c.score))
    rank = {c.id: i for i, c in enumerate(usable, 1)}
    rest = sorted((c for c in caps if c.status not in USABLE), key=lambda c: (c.status, c.domain))
    counts: dict[str, int] = {}
    for c in caps:
        counts[c.status] = counts.get(c.status, 0) + 1
    return {
        "area": area,
        "sources": [_cap_out(c, rank.get(c.id), srcs.get(c.domain)) for c in [*usable, *rest]],
        "counts": counts,
        "autonomy": bool(load_yaml("registry.yaml").get("autonomy")),
    }


@router.get("/sources/changes", dependencies=[Admin])
async def source_changes(days: int = 30, area: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    since = now() - timedelta(days=max(1, min(days, 365)))
    async with sessionmaker()() as s:
        q = (
            select(RegistryChange)
            .where(RegistryChange.created_at >= since, RegistryChange.reason != "")
            .order_by(RegistryChange.created_at.desc())
            .limit(max(1, min(limit, 1000)))
        )
        rows = [_change_out(c) for c in (await s.execute(q)).scalars()]
    rows = [r for r in rows if not str(r["reason"]).startswith("seed")] or rows  # the seed is history, not news
    return [r for r in rows if area is None or r["area"] in (None, area)]


@router.get("/sources/{domain}", dependencies=[Admin])
async def source(domain: str) -> dict[str, Any]:
    async with sessionmaker()() as s:
        src = await s.get(SourceRow, domain)
        if src is None:
            raise HTTPException(status_code=404, detail="not found")
        caps = list((await s.execute(select(CapabilityRow).where(CapabilityRow.domain == domain))).scalars())
        changes = list(
            (
                await s.execute(
                    select(RegistryChange)
                    .where(RegistryChange.domain == domain)
                    .order_by(RegistryChange.created_at.desc())
                    .limit(50)
                )
            ).scalars()
        )
        signals = list(
            (
                await s.execute(
                    select(TruthSignal)
                    .where(TruthSignal.capability_id.in_([c.id for c in caps]))
                    .order_by(TruthSignal.created_at.desc())
                    .limit(50)
                )
            ).scalars()
        )
    return {
        "source": {c.name: getattr(src, c.name) for c in SourceRow.__table__.columns},
        "capabilities": [_cap_out(c, None, src) for c in caps],
        "changes": [_change_out(c) for c in changes],
        "signals": [
            {
                "at": x.created_at,
                "kind": x.kind,
                "verdict": x.verdict,
                "weight": x.weight,
                "blame": x.blame,
                "attribute": x.attribute,
                "variant_id": x.variant_id,
            }
            for x in signals
        ],
    }


async def _owner_change(
    domain: str, change: str, apply: Callable[[Any, SourceRow, list[CapabilityRow]], Any], reason: str
) -> dict[str, Any]:
    async with sessionmaker()() as s:
        src = await s.get(SourceRow, domain)
        if src is None:
            raise HTTPException(status_code=404, detail="not found")
        caps = list((await s.execute(select(CapabilityRow).where(CapabilityRow.domain == domain))).scalars())
        before = {"frozen": src.frozen, "statuses": {c.id: c.status for c in caps}}
        apply(s, src, caps)
        s.add(
            RegistryChange(
                author="owner",
                domain=domain,
                change=change,
                before=before,
                after={"frozen": src.frozen, "statuses": {c.id: c.status for c in caps}},
                reason=reason,
            )
        )
        await s.commit()
    prom.inc("registry_changes", change=change, author="owner")
    return {"domain": domain, "change": change}


@router.post("/sources/{domain}/freeze", dependencies=[Admin])
async def freeze(domain: str) -> dict[str, Any]:
    return await _owner_change(
        domain,
        "frozen",
        lambda s, src, caps: setattr(src, "frozen", True),
        "frozen by the owner: the system may not change this source",
    )


@router.post("/sources/{domain}/unfreeze", dependencies=[Admin])
async def unfreeze(domain: str) -> dict[str, Any]:
    return await _owner_change(
        domain, "frozen", lambda s, src, caps: setattr(src, "frozen", False), "unfrozen by the owner"
    )


@router.post("/sources/{domain}/block", dependencies=[Admin])
async def block(domain: str) -> dict[str, Any]:
    def apply(s: Any, src: SourceRow, caps: list[CapabilityRow]) -> None:
        for c in caps:
            c.status, c.status_since = "blocked", now()

    return await _owner_change(domain, "blocked", apply, "blocked by the owner")


@router.post("/sources/changes/{change_id}/revert", dependencies=[Admin])
async def revert(change_id: str) -> dict[str, Any]:
    deny = tuple(str(x).lower() for x in load_yaml("sources.yaml").get("denylist") or [])
    async with sessionmaker()() as s:
        ch = await s.get(RegistryChange, change_id)
        if ch is None:
            raise HTTPException(status_code=404, detail="not found")
        if ch.held or ch.reverted_by is not None or ch.change in ("added", "reverted"):
            raise HTTPException(status_code=409, detail="this change cannot be reverted")
        src = await s.get(SourceRow, ch.domain)
        later = (
            await s.execute(
                select(RegistryChange.id)
                .where(
                    RegistryChange.domain == ch.domain,
                    RegistryChange.created_at > ch.created_at,
                    RegistryChange.capability_id == ch.capability_id,
                    RegistryChange.held.is_(False),
                    RegistryChange.change != "reordered",
                )
                .limit(1)
            )
        ).first()
        if later:
            raise HTTPException(status_code=409, detail="revert the later change of this source first")
        if ch.capability_id:
            cap = await s.get(CapabilityRow, ch.capability_id)
            target = (ch.before or {}).get("status")
            if cap is not None and target:
                hard = src is not None and (src.access in ACCESS_BLOCKING or denied(src.domain, deny))
                if hard and target != "blocked":
                    raise HTTPException(status_code=409, detail="hard limit: change config")
                cap.status, cap.status_since = target, now()
        else:  # an owner change of the whole source (freeze / block)
            caps = list((await s.execute(select(CapabilityRow).where(CapabilityRow.domain == ch.domain))).scalars())
            prev = (ch.before or {}).get("statuses") or {}
            hard = src is not None and (src.access in ACCESS_BLOCKING or denied(src.domain, deny))
            for c in caps:
                if c.id in prev and not (hard and prev[c.id] != "blocked"):
                    c.status = prev[c.id]
            if src is not None and "frozen" in (ch.before or {}):
                src.frozen = bool(ch.before["frozen"])
        rev = RegistryChange(
            author="owner",
            capability_id=ch.capability_id,
            domain=ch.domain,
            change="reverted",
            before=ch.after,
            after=ch.before,
            reason=f"owner reverted: {ch.reason}"[:500],
        )
        s.add(rev)
        await s.flush()
        ch.reverted_by = rev.id
        await s.commit()
    prom.inc("registry_changes", change="reverted", author="owner")
    return {"reverted": change_id, "by": rev.id}


# --- Acquisition engine (spec 011 US6, FR-021): Parsers, Changes, the accuracy drill-down, the engine strip ------


def _http(e: Exception) -> HTTPException:
    if isinstance(e, admin_api.NotFound):
        return HTTPException(status_code=404, detail="not found")
    return HTTPException(status_code=409, detail=str(e))


@router.get("/parsers", dependencies=[Admin])
async def parsers() -> list[dict[str, Any]]:
    return await admin_api.parsers()


@router.get("/parsers/{reader}", dependencies=[Admin])
async def parser(reader: str) -> dict[str, Any]:
    try:
        return await admin_api.parser(reader)
    except admin_api.NotFound as e:
        raise _http(e) from e


class RollbackIn(BaseModel):
    to: str = Field(min_length=3, max_length=80)


@router.post("/parsers/{reader}/rollback", dependencies=[Admin])
async def parser_rollback(reader: str, body: RollbackIn) -> dict[str, Any]:
    try:
        return await admin_api.rollback_parser(reader, body.to)
    except (admin_api.NotFound, admin_api.Conflict) as e:
        raise _http(e) from e


@router.post("/parsers/{reader}/freeze", dependencies=[Admin])
async def parser_freeze(reader: str) -> dict[str, Any]:
    try:
        return await admin_api.freeze_parser(reader, True)
    except admin_api.NotFound as e:
        raise _http(e) from e


@router.post("/parsers/{reader}/unfreeze", dependencies=[Admin])
async def parser_unfreeze(reader: str) -> dict[str, Any]:
    try:
        return await admin_api.freeze_parser(reader, False)
    except admin_api.NotFound as e:
        raise _http(e) from e


@router.get("/changes", dependencies=[Admin])
async def all_changes(
    origin: Literal["engine", "registry"] | None = None,
    agent: str | None = None,
    object_kind: str | None = None,
    status: str | None = None,
    days: int = 30,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Every automatic change of every agent in one list: the engine journal and the registry journal."""
    return await admin_api.changes(origin, agent or None, object_kind or None, status or None, days, limit)


@router.get("/changes/{change_id}", dependencies=[Admin])
async def one_change(change_id: str) -> dict[str, Any]:
    try:
        return await admin_api.change(change_id)
    except admin_api.NotFound as e:
        raise _http(e) from e


async def _origin(change_id: str) -> str:
    try:
        return await admin_api.origin_of(change_id)
    except admin_api.NotFound as e:
        raise _http(e) from e


@router.post("/changes/{change_id}/revert", dependencies=[Admin])
async def change_revert(change_id: str) -> dict[str, Any]:
    if await _origin(change_id) == "registry":
        return await revert(change_id)  # 010's revert of a registry change
    try:
        return await admin_api.revert_change(change_id)
    except (admin_api.NotFound, admin_api.Conflict) as e:
        raise _http(e) from e


@router.post("/changes/{change_id}/reject", dependencies=[Admin])
async def change_reject(change_id: str) -> dict[str, Any]:
    if await _origin(change_id) == "registry":
        raise HTTPException(status_code=409, detail="a registry change is applied at once: revert it instead")
    try:
        return await admin_api.reject_change(change_id)
    except (admin_api.NotFound, admin_api.Conflict) as e:
        raise _http(e) from e


class ForbidIn(BaseModel):
    days: int | None = Field(default=30, ge=1, le=3650)


@router.post("/changes/{change_id}/forbid-similar", dependencies=[Admin])
async def change_forbid(change_id: str, body: ForbidIn) -> dict[str, Any]:
    """Forbid similar changes on this object: the object is frozen (a registry source, a parser)."""
    if await _origin(change_id) == "registry":
        async with sessionmaker()() as s:
            ch = await s.get(RegistryChange, change_id)
            domain = ch.domain if ch else ""
        await freeze(domain)
        return {"object_kind": "source", "object_key": domain, "frozen": True, "blocked": False, "until": None}
    try:
        return await admin_api.forbid_similar(change_id, body.days)
    except (admin_api.NotFound, admin_api.Conflict) as e:
        raise _http(e) from e


@router.get("/accuracy", dependencies=[Admin])
async def accuracy(days: int = 30) -> dict[str, Any]:
    """The accuracy KPI against the baseline, by kind of data, and the components to blame (click 1 picks one)."""
    return await admin_api.accuracy(days)


@router.get("/accuracy/{component:path}/values", dependencies=[Admin])
async def accuracy_values(component: str, days: int = 30) -> list[dict[str, Any]]:
    """The wrong values blamed on one component (`parser:km77@v4`, `source:motor.es`, …); click 2 picks one."""
    return await admin_api.wrong_values(component, days)


@router.get("/values/{claim_id}", dependencies=[Admin])
async def value(claim_id: str) -> dict[str, Any]:
    """One value with its source, producer, quote, page snapshot and signals (click 3)."""
    try:
        return await admin_api.value(claim_id)
    except admin_api.NotFound as e:
        raise _http(e) from e


@router.get("/snapshots/{snapshot_id}/text", dependencies=[Admin], response_class=PlainTextResponse)
async def snapshot_text(snapshot_id: str, around: str | None = Query(default=None, max_length=2000)) -> str:
    """The page text (at most 4,000 characters, plain text, never HTML) around the quote."""
    try:
        return await admin_api.snapshot_text(snapshot_id, around)
    except admin_api.NotFound as e:
        raise _http(e) from e


@router.get("/engine", dependencies=[Admin])
async def engine() -> dict[str, Any]:
    """The header strip: worker beat, tasks, today's budgets, baseline, autonomy, open changes."""
    return await admin_api.engine()
