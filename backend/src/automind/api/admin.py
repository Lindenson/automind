"""Admin API (spec 010 US4, contracts/admin-api.md): two screens — Top problems and Sources.

Every route requires the admin token (or this machine when none is set). Detailed metrics and alerts are in
Prometheus, not here (FR-029).
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from automind.api import access
from automind.config import settings
from automind.infrastructure.config import load_yaml
from automind.infrastructure.db.models import InsightIssue, now
from automind.infrastructure.db.session import sessionmaker
from automind.insight.domain.issue_text import copy_text

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
