"""Parser versions in the database (spec 011 US4, data-model "Migration 0022"): load the running versions, look one
up by key, count zero streaks, and degrade a version — journalled in `acq_changes` by `system` and handed to the
parser doctor (`doctor:<key>`; its handler arrives with US5, until then the task waits in the queue)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text, update

from automind.acquisition.domain.drift import Drift
from automind.acquisition.parsing.spec import ParserSpec
from automind.shared.infrastructure.db import AcqChange, Parser, ParserVersion, sessionmaker, uid
from automind.shared.provenance.versions import parse_key, spec_hash

log = logging.getLogger(__name__)
RUNNING = ("active", "degraded")  # a degraded version keeps running until a replacement is accepted (R12)
DOCTOR = "parser_doctor"


@dataclass(frozen=True)
class Version:
    key: str
    spec: ParserSpec
    status: str
    zero_streak: int = 0


async def running() -> list[Version]:
    """The version each parser runs: its `active_version`, while that version is active or degraded."""
    async with sessionmaker()() as s:
        rows = (
            await s.execute(
                select(ParserVersion)
                .join(Parser, Parser.reader == ParserVersion.reader)
                .where(Parser.active_version == ParserVersion.version, ParserVersion.status.in_(RUNNING))
            )
        ).scalars()
        out = []
        for r in rows:
            try:
                out.append(Version(r.key, ParserSpec.model_validate(r.spec), r.status, r.zero_streak))
            except ValueError:
                log.warning("parser.bad_stored_spec key=%s", r.key)
        return out


async def allowed_domains(domains: list[str]) -> set[str]:
    """Spec domains whose registry source has access "ok" and is not blocked (replaces favourites' tos_checked)."""
    if not domains:
        return set()
    q = text("SELECT domain FROM sources WHERE access = 'ok' AND domain = ANY(:d)")
    async with sessionmaker()() as s:
        return {str(d) for (d,) in (await s.execute(q, {"d": domains})).all()}


async def version(key: str) -> Version | None:
    parse_key(key)  # ValueError for a malformed key
    async with sessionmaker()() as s:
        r = await s.get(ParserVersion, key)
    if r is None:
        return None
    return Version(r.key, ParserSpec.model_validate(r.spec), r.status, r.zero_streak)


async def add_zero_streak(key: str, zeros: int, reset: bool) -> tuple[int, str] | None:
    """Add `zeros` pages with no field to the version's streak (after a reset when a page had fields in between);
    returns (streak, status)."""
    q = text(
        "UPDATE parser_versions SET zero_streak = CASE WHEN :reset THEN :n ELSE zero_streak + :n END "
        "WHERE key = :k RETURNING zero_streak, status"
    )
    async with sessionmaker()() as s:
        got = (await s.execute(q, {"k": key, "n": zeros, "reset": reset})).first()
        await s.commit()
    return (int(got[0]), str(got[1])) if got else None


def explanation(key: str, drift: Drift, since: datetime | None = None) -> str:
    """One sentence with the numbers, built by code: "km77 parser v1 degraded: 5 pages in a row with no fields since
    2026-11-05 10:02 UTC"."""
    reader, n = parse_key(key)
    tail = f" since {since.astimezone(UTC):%Y-%m-%d %H:%M} UTC" if since is not None else ""
    return f"{reader} parser v{n} degraded: {drift.reason}{tail}"


async def degrade(key: str, drift: Drift, *, since: datetime | None = None,
                  evidence: dict[str, Any] | None = None) -> str | None:  # fmt: skip
    """Mark an active version degraded with the drift's reason, journal it and enqueue the parser doctor. Returns the
    change id, or None when the version was not active (already degraded, retired, …)."""
    from automind.acquisition.worker import queue  # noqa: PLC0415

    now = datetime.now(UTC)
    sentence = explanation(key, drift, since)
    async with sessionmaker()() as s:
        reader = (
            await s.execute(
                update(ParserVersion)
                .where(ParserVersion.key == key, ParserVersion.status == "active")
                .values(status="degraded", degraded_reason=drift.reason)
                .returning(ParserVersion.reader)
            )
        ).scalar_one_or_none()
        if reader is None:
            return None
        diff = {"status": ["active", "degraded"], "degraded_reason": drift.reason}
        change = AcqChange(
            id=uid(), created_at=now, author="system", object_kind="parser", object_key=reader, from_version=key,
            to_version=key, diff=diff, diff_hash=spec_hash(diff), reason=f"drift:{drift.kind}",
            evidence={"signals": drift.signals, **(evidence or {})}, gates={}, status="accepted",
            explanation=sentence, cost_eur=0, closed_at=now,
        )  # fmt: skip
        s.add(change)
        await s.commit()
    log.warning("parser.degraded key=%s reason=%s", key, drift.reason,
                extra={"event": "parser.degraded", "version": key, "kind": drift.kind})  # fmt: skip
    await queue.enqueue(DOCTOR, {"version": key, "reason": drift.kind, "change_id": change.id},
                        dedupe_key=f"doctor:{key}")  # fmt: skip
    return change.id
