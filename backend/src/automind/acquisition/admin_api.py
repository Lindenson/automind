"""What the admin page reads from, and asks of, the acquisition engine (spec 011 US6, FR-021, contracts/admin-api.md).

The admin API (`automind.delivery.web.admin`) reaches the engine only through this module (import contract
`api-uses-engine-facades`). Reads: parsers with their versions and daily metrics, the change journal of every agent
(engine `acq_changes` and registry `registry_changes` in one shape), the accuracy drill-down down to the page text,
the engine status strip. Owner levers: roll a parser back, freeze it, revert / reject a journalled engine change,
forbid similar changes on its object. Every owner action is journalled in `acq_changes` with `author=owner`.

The change journal is read generically: unknown statuses, extra gates and extra columns added by later stages pass
through unchanged. Tables of later stages (`acq_experiments`, `change_blocks`, `prompt_versions`, `rule_overrides`,
`role_model_overrides`) are used only when they exist.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, text

from automind.shared.infrastructure.config.loader import load_yaml
from automind.shared.infrastructure.db.models import (
    OPEN_CHANGE_STATUSES,
    AcqChange,
    AcqWorker,
    CapabilityRow,
    Claim,
    ComponentReputation,
    Evidence,
    KpiBaseline,
    PageSnapshot,
    Parser,
    ParserDaily,
    ParserVersion,
    RegistryChange,
    TruthSignal,
    Variant,
    uid,
)
from automind.shared.infrastructure.db.session import sessionmaker
from automind.shared.provenance.versions import parse_key, spec_hash

log = logging.getLogger(__name__)

OWNER = "owner"
RUNNING = ("active", "degraded")
ACCEPTED = ("accepted", "watch", "kept")  # a change in effect: the owner may revert it
IN_GATES = ("proposed", "replay", "shadow")  # not in effect yet: the owner may reject it
CANARY = ("replay", "shadow", "watch")
WAS_ACTIVE = ("superseded", "degraded", "retired", "active")
TEXT_WINDOW = 4000
DAILY_DAYS = 60


class NotFound(LookupError):
    """No such parser, change, claim or snapshot."""


class Conflict(ValueError):
    """The owner's action is not possible in the object's current state (HTTP 409)."""


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(d: date | datetime | None) -> str | None:
    return d.isoformat() if d is not None else None


def _f(v: Any) -> float | None:
    return float(v) if v is not None else None


async def _table(s: Any, name: str) -> bool:
    return bool((await s.execute(text("SELECT to_regclass(:n) IS NOT NULL"), {"n": f"public.{name}"})).scalar())


# --- Parsers ---------------------------------------------------------------------------------------------------------


def _agg(rows: Iterable[ParserDaily]) -> dict[str, Any]:
    rows = list(rows)
    pages = sum(r.pages for r in rows)
    fields = sum(r.fields_total for r in rows)
    read = sum(r.rows_read for r in rows)
    acc = sum(r.rows_accepted for r in rows)
    return {
        "pages": pages,
        "fields_per_page": round(fields / pages, 3) if pages else None,
        "pass_rate": round(acc / read, 4) if read else None,
        "zero_pages": sum(r.zero_pages for r in rows),
    }


def _version_out(v: ParserVersion) -> dict[str, Any]:
    return {
        "key": v.key,
        "version": v.version,
        "status": v.status,
        "author": v.author,
        "created_at": v.created_at,
        "activated_at": v.activated_at,
        "change_id": v.change_id,
        "degraded_reason": v.degraded_reason,
        "zero_streak": v.zero_streak,
    }


def _drift_signals(changes: Iterable[AcqChange]) -> list[dict[str, Any]]:
    """Drift journal rows (`system`, reason `drift:<kind>`) as signals, one per kind found, newest first."""
    out = []
    for c in sorted(changes, key=lambda c: c.created_at, reverse=True):
        if c.author != "system" or not (c.reason or "").startswith("drift:"):
            continue
        found = (c.evidence or {}).get("signals") or {}
        kinds = list(found) if isinstance(found, dict) and found else [c.reason.removeprefix("drift:")]
        for k in kinds:
            out.append(
                {
                    "day": _iso(c.created_at.date()),
                    "at": c.created_at,
                    "kind": k,
                    "version": c.from_version,
                    "detail": c.explanation,
                    "values": found.get(k) if isinstance(found, dict) else None,
                    "change_id": c.id,
                }
            )
    return out


async def _experiments(s: Any, ids: list[str]) -> dict[str, dict[str, Any]]:
    if not ids or not await _table(s, "acq_experiments"):
        return {}
    rows = (await s.execute(text("SELECT * FROM acq_experiments WHERE change_id = ANY(:ids)"), {"ids": ids})).mappings()
    return {str(r["change_id"]): dict(r) for r in rows}


def _canary(c: AcqChange | None, exp: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    if c is None:
        return None
    gates = c.gates or {}
    e = exp.get(c.id) or {}
    phase = e.get("phase") or c.status
    g = gates.get(phase) if isinstance(gates.get(phase), dict) else {}
    watch = gates.get("watch") if isinstance(gates.get("watch"), dict) else {}
    return {
        "change_id": c.id,
        "phase": phase,
        "ends_at": e.get("ends_at") or g.get("ends_at"),
        "day": watch.get("day"),
        "of": watch.get("of"),
    }


async def _parsers(readers: list[str] | None, daily_days: int) -> list[dict[str, Any]]:
    today = _now().date()
    since = today - timedelta(days=max(daily_days, 37))
    async with sessionmaker()() as s:
        pq = select(Parser).order_by(Parser.reader)
        if readers is not None:
            pq = pq.where(Parser.reader.in_(readers))
        parsers = list((await s.execute(pq)).scalars())
        names = [p.reader for p in parsers]
        if not names:
            return []
        versions = list((await s.execute(select(ParserVersion).where(ParserVersion.reader.in_(names)))).scalars())
        keys = [v.key for v in versions]
        daily = list(
            (
                await s.execute(select(ParserDaily).where(ParserDaily.version_key.in_(keys), ParserDaily.day >= since))
            ).scalars()
        )
        changes = list(
            (
                await s.execute(
                    select(AcqChange).where(
                        AcqChange.object_kind == "parser",
                        AcqChange.object_key.in_(names),
                        AcqChange.created_at >= _now() - timedelta(days=DAILY_DAYS),
                    )
                )
            ).scalars()
        )
        open_ = [c for c in changes if c.status in CANARY and c.closed_at is None]
        exp = await _experiments(s, [c.id for c in open_])
    by_reader: dict[str, list[ParserVersion]] = defaultdict(list)
    for v in versions:
        by_reader[v.reader].append(v)
    reader_of = {v.key: v.reader for v in versions}
    daily_of: dict[str, list[ParserDaily]] = defaultdict(list)
    for d in daily:
        daily_of[reader_of[d.version_key]].append(d)
    out = []
    for p in parsers:
        vs = sorted(by_reader[p.reader], key=lambda v: v.version, reverse=True)
        active = next((v for v in vs if v.version == p.active_version), None)
        rows = daily_of[p.reader]
        last = [r for r in rows if active is not None and r.version_key == active.key and r.day > today - timedelta(7)]
        base = [r for r in rows if today - timedelta(days=37) < r.day <= today - timedelta(days=7)]
        signals = _drift_signals(c for c in changes if c.object_key == p.reader)
        drift = None
        if active is not None and active.status == "degraded":
            drift = {"kind": "degraded", "detail": active.degraded_reason, "version": active.key}
        if active is not None:
            fresh = [
                x
                for x in signals
                if x["version"] == active.key and (active.activated_at is None or x["at"] >= active.activated_at)
            ]
            drift = fresh[0] if fresh else drift
        canary = next(
            (c for c in sorted(open_, key=lambda c: c.created_at, reverse=True) if c.object_key == p.reader), None
        )
        b = _agg(base)
        recent = sorted((r for r in rows if r.day > today - timedelta(days=30)), key=lambda r: r.day)
        by_day: dict[date, list[ParserDaily]] = defaultdict(list)
        for r in recent:
            by_day[r.day].append(r)
        spark = []
        for d, v in by_day.items():
            a = _agg(v)
            spark.append({"day": _iso(d), "fields_per_page": a["fields_per_page"], "pass_rate": a["pass_rate"]})
        out.append(
            {
                "reader": p.reader,
                "domains": list(p.domains or []),
                "page_type": p.page_type,
                "frozen": bool(p.frozen),
                "active": active.key if active else None,
                "active_status": active.status if active else None,
                "versions": [_version_out(v) for v in vs],
                "last_7d": _agg(last),
                "spark_30d": spark,  # the reader's daily fields per page and pass rate (all versions), 30 days
                "baseline_30d": {
                    "fields_per_page": b["fields_per_page"],
                    "pass_rate": b["pass_rate"],
                    "pages": b["pages"],
                },
                "drift": drift,
                "canary": _canary(canary, exp),
                "_daily": rows,
                "_signals": signals,
                "_specs": {v.key: v.spec for v in vs},
            }
        )
    return out


def _public(p: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in p.items() if not k.startswith("_")}


async def parsers() -> list[dict[str, Any]]:
    """Every parser: versions with status, 7-day yield and pass rate of the active version vs the reader's 30 days
    before, a drift since the active version's activation, a running canary."""
    return [_public(p) for p in await _parsers(None, 37)]


async def parser(reader: str) -> dict[str, Any]:
    got = await _parsers([reader], DAILY_DAYS)
    if not got:
        raise NotFound(reader)
    p = got[0]
    since = _now().date() - timedelta(days=DAILY_DAYS)
    daily = sorted((r for r in p["_daily"] if r.day >= since), key=lambda r: (r.day, r.version_key))
    return {
        **_public(p),
        "daily": [
            {
                "version_key": r.version_key,
                "day": _iso(r.day),
                "pages": r.pages,
                "fields_per_page": round(r.fields_per_page, 3),
                "pass_rate": r.pass_rate,
                "zero_pages": r.zero_pages,
                "structure_hash": r.structure_hash,
                "structure_sim": r.structure_sim,
            }
            for r in daily
        ],
        "drift_signals": p["_signals"],
        "specs": p["_specs"],
    }


def _journal(
    kind: str, key: str, frm: str | None, to: str | None, diff: dict[str, Any], reason: str, sentence: str
) -> AcqChange:
    t = _now()
    return AcqChange(
        id=uid(),
        created_at=t,
        author=OWNER,
        object_kind=kind,
        object_key=key,
        from_version=frm,
        to_version=to,
        diff=diff,
        diff_hash=spec_hash(diff),
        reason=reason,
        evidence={},
        gates={},
        status="accepted",
        explanation=sentence,
        cost_eur=0,
        closed_at=t,
    )


async def _activate(s: Any, reader: str, to: ParserVersion) -> str | None:
    """Make `to` the running version of its reader (the running one becomes superseded); returns the former key."""
    p = await s.get(Parser, reader)
    current = None
    for v in (
        await s.execute(select(ParserVersion).where(ParserVersion.reader == reader, ParserVersion.status.in_(RUNNING)))
    ).scalars():
        if v.key != to.key:
            if v.version == p.active_version:
                current = v.key
            v.status = "superseded"
    to.status, to.activated_at, to.degraded_reason, to.zero_streak = "active", _now(), None, 0
    p.active_version = to.version
    return current


async def _close(s: Any, c: AcqChange, status: str, by: str | None) -> None:
    c.status, c.closed_at = status, _now()
    if by:
        c.reverted_by = by


async def rollback_parser(reader: str, to: str) -> dict[str, Any]:
    """Re-activate an earlier version of the reader; the change that installed the current one becomes `reverted`."""
    async with sessionmaker()() as s:
        p = await s.get(Parser, reader)
        if p is None:
            raise NotFound(reader)
        tv = await s.get(ParserVersion, to)
        if tv is None or tv.reader != reader:
            raise Conflict(f"{to} is not a version of {reader}")
        if tv.version == p.active_version and tv.status in RUNNING:
            raise Conflict(f"{to} is the running version")
        if tv.activated_at is None or tv.status not in WAS_ACTIVE:
            raise Conflict(f"{to} was never active: only a previous version can be restored")
        cur_key = f"{reader}@v{p.active_version}" if p.active_version else None
        await _activate(s, reader, tv)
        cur_n = parse_key(cur_key)[1] if cur_key else None
        row = _journal(
            "parser",
            reader,
            cur_key,
            to,
            {"active": [cur_key, to]},
            "owner rollback",
            f"{reader} parser rolled back by the owner: v{cur_n} → v{tv.version}",
        )
        s.add(row)
        await s.flush()
        installed = (
            await s.execute(
                select(AcqChange).where(
                    AcqChange.object_kind == "parser",
                    AcqChange.object_key == reader,
                    AcqChange.to_version == cur_key,
                    AcqChange.author.notin_(("system", OWNER)),
                    AcqChange.status.in_(ACCEPTED),
                    AcqChange.reverted_by.is_(None),
                )
            )
        ).scalars()
        reverted = []
        for c in installed:
            await _close(s, c, "reverted", row.id)
            reverted.append(c.id)
        await s.commit()
    log.info("admin.parser_rollback reader=%s to=%s", reader, to)
    return {"reader": reader, "active": to, "change_id": row.id, "reverted": reverted}


async def freeze_parser(reader: str, frozen: bool) -> dict[str, Any]:
    """Freeze (no agent proposal targets the reader) or unfreeze, journalled."""
    async with sessionmaker()() as s:
        p = await s.get(Parser, reader)
        if p is None:
            raise NotFound(reader)
        before = bool(p.frozen)
        p.frozen = frozen
        word = "frozen" if frozen else "unfrozen"
        row = _journal(
            "parser",
            reader,
            None,
            None,
            {"frozen": [before, frozen]},
            f"owner {word}",
            f"{reader} parser {word} by the owner",
        )
        s.add(row)
        await s.commit()
    return {"reader": reader, "frozen": frozen, "change_id": row.id}


# --- Changes ---------------------------------------------------------------------------------------------------------


def _verdicts(gates: dict[str, Any] | None) -> dict[str, Any] | None:
    """The gates of a change with their verdicts and short facts (no bulky metrics) for the list."""
    if not gates:
        return {}
    out: dict[str, Any] = {}
    for name, g in gates.items():
        if isinstance(g, dict):
            out[name] = {k: v for k, v in g.items() if not isinstance(v, dict | list)}
        else:
            out[name] = g
    return out


def _revertible(c: AcqChange) -> bool:
    """An agent's change in effect (accepted, under watch or kept) that nobody reverted; drift rows (`system`) and
    the owner's own rows are not changes to revert."""
    return c.status in ACCEPTED and c.reverted_by is None and c.author not in ("system", OWNER)


def _engine_out(c: AcqChange) -> dict[str, Any]:
    return {
        "id": c.id,
        "origin": "engine",
        "created_at": c.created_at,
        "author": c.author,
        "object_kind": c.object_kind,
        "object_key": c.object_key,
        "from_version": c.from_version,
        "to_version": c.to_version,
        "status": c.status,
        "explanation": c.explanation,
        "reason": c.reason,
        "gates": _verdicts(c.gates),
        "revertible": _revertible(c),
        "rejectable": c.status in IN_GATES and c.closed_at is None,
        "closed_at": c.closed_at,
    }


def _registry_status(c: RegistryChange) -> str:
    if c.reverted_by is not None:
        return "reverted"
    return "held" if c.held else "accepted"


def _registry_out(c: RegistryChange) -> dict[str, Any]:
    before, after = c.before or {}, c.after or {}
    return {
        "id": c.id,
        "origin": "registry",
        "created_at": c.created_at,
        "author": c.author,
        "object_kind": "source",
        "object_key": c.domain,
        "from_version": before.get("status") if isinstance(before.get("status"), str) else None,
        "to_version": after.get("status") if isinstance(after.get("status"), str) else c.change,
        "status": _registry_status(c),
        "explanation": c.reason,
        "reason": c.change,
        "gates": None,
        "revertible": not c.held and c.reverted_by is None and c.change not in ("added", "reverted"),
        "rejectable": False,
        "closed_at": None,
    }


async def changes(
    origin: str | None = None,
    agent: str | None = None,
    object_kind: str | None = None,
    status: str | None = None,
    days: int = 30,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Every automatic (and owner) change of the last `days`, newest first, engine and registry rows in one shape."""
    since = _now() - timedelta(days=max(1, min(days, 365)))
    limit = max(1, min(limit, 500))
    rows: list[dict[str, Any]] = []
    async with sessionmaker()() as s:
        if origin in (None, "engine"):
            q = select(AcqChange).where(AcqChange.created_at >= since)
            if agent:
                q = q.where(AcqChange.author.contains(agent))
            if object_kind:
                q = q.where(AcqChange.object_kind == object_kind)
            if status:
                q = q.where(AcqChange.status == status)
            rows += [
                _engine_out(c)
                for c in (await s.execute(q.order_by(AcqChange.created_at.desc()).limit(limit))).scalars()
            ]
        if origin in (None, "registry") and object_kind in (None, "source"):
            q = _registry_query(since, agent, status)
            rows += [
                _registry_out(c)
                for c in (await s.execute(q.order_by(RegistryChange.created_at.desc()).limit(limit))).scalars()
            ]
    rows.sort(key=lambda r: r["created_at"], reverse=True)
    return rows[:limit]


def _registry_query(since: datetime, agent: str | None, status: str | None) -> Any:
    """Registry journal rows of the window (the seed is history, not news), filtered like the engine's."""
    q = select(RegistryChange).where(
        RegistryChange.created_at >= since, RegistryChange.reason != "", RegistryChange.reason.notlike("seed%")
    )
    if agent:
        q = q.where(RegistryChange.author.contains(agent.removeprefix("agent:")))
    if status == "reverted":
        return q.where(RegistryChange.reverted_by.is_not(None))
    if status == "held":
        return q.where(RegistryChange.held.is_(True), RegistryChange.reverted_by.is_(None))
    if status == "accepted":
        return q.where(RegistryChange.held.is_(False), RegistryChange.reverted_by.is_(None))
    return q.where(text("false")) if status else q


async def origin_of(change_id: str) -> str:
    async with sessionmaker()() as s:
        if await s.get(AcqChange, change_id) is not None:
            return "engine"
        if await s.get(RegistryChange, change_id) is not None:
            return "registry"
    raise NotFound(change_id)


async def change(change_id: str) -> dict[str, Any]:
    """One change with its diff, reason, evidence, gates with old/new metrics, KPIs before/after, cost, and the
    experiment's daily metrics when there is one."""
    async with sessionmaker()() as s:
        c = await s.get(AcqChange, change_id)
        if c is not None:
            exp = (await _experiments(s, [c.id])).get(c.id)
            return {
                **_engine_out(c),
                "diff": c.diff,
                "diff_hash": c.diff_hash,
                "evidence": c.evidence or {},
                "gates": c.gates or {},
                "metrics_before": c.metrics_before,
                "metrics_after": c.metrics_after,
                "cost_eur": float(c.cost_eur or 0),
                "reverted_by": c.reverted_by,
                "experiment": exp,
            }
        r = await s.get(RegistryChange, change_id)
        if r is None:
            raise NotFound(change_id)
        return {
            **_registry_out(r),
            "diff": {"before": r.before or {}, "after": r.after or {}},
            "evidence": r.evidence or {},
            "gates": None,
            "metrics_before": None,
            "metrics_after": None,
            "cost_eur": 0.0,
            "reverted_by": r.reverted_by,
            "experiment": None,
            "capability_id": r.capability_id,
            "held": r.held,
        }


async def _undo_object(s: Any, c: AcqChange) -> str:
    """Put the change's object back as it was before the change; returns a short phrase for the sentence."""
    if c.object_kind == "parser":
        if not c.from_version:
            raise Conflict("this parser change has no previous version")
        prev = await s.get(ParserVersion, c.from_version)
        if prev is None or prev.reader != c.object_key:
            raise Conflict(f"{c.from_version} no longer exists")
        await _activate(s, c.object_key, prev)
        return f"{c.from_version} active again"
    if c.object_kind == "prompt" and await _table(s, "prompt_versions") and c.from_version and c.to_version:
        await s.execute(text("UPDATE prompt_versions SET status = 'superseded' WHERE key = :k"), {"k": c.to_version})
        await s.execute(
            text("UPDATE prompt_versions SET status = 'active', activated_at = now() WHERE key = :k"),
            {"k": c.from_version},
        )
        return f"{c.from_version} active again"
    if c.object_kind == "role_model" and await _table(s, "role_model_overrides"):
        await s.execute(text("UPDATE role_model_overrides SET active = false WHERE change_id = :id"), {"id": c.id})
        return "model override removed"
    if c.object_kind == "rule" and await _table(s, "rule_overrides"):
        await s.execute(text("UPDATE rule_overrides SET status = 'superseded' WHERE change_id = :id"), {"id": c.id})
        return "rule override removed"
    raise Conflict(f"a {c.object_kind} change cannot be reverted from here")


async def revert_change(change_id: str) -> dict[str, Any]:
    """Owner revert of an accepted engine change: its object goes back to `from_version` (or loses the override),
    the change becomes `reverted`, an owner row is journalled."""
    async with sessionmaker()() as s:
        c = await s.get(AcqChange, change_id)
        if c is None:
            raise NotFound(change_id)
        if c.status in IN_GATES:
            raise Conflict("this change is not accepted yet: reject it instead")
        if not _revertible(c):
            raise Conflict(f"a {c.status} change by {c.author} cannot be reverted")
        later = (
            await s.execute(
                select(AcqChange.id)
                .where(
                    AcqChange.object_kind == c.object_kind,
                    AcqChange.object_key == c.object_key,
                    AcqChange.created_at > c.created_at,
                    AcqChange.id != c.id,
                    AcqChange.author != "system",
                    AcqChange.status.in_(ACCEPTED),
                    AcqChange.reverted_by.is_(None),
                    AcqChange.to_version.is_not(None),
                )
                .limit(1)
            )
        ).first()
        if later:
            raise Conflict("revert the later change of this object first")
        what = await _undo_object(s, c)
        row = _journal(
            c.object_kind,
            c.object_key,
            c.to_version,
            c.from_version,
            {"reverted": c.id, "active": [c.to_version, c.from_version]},
            f"owner revert of {c.id}",
            f"{c.object_key} {c.object_kind} change {c.from_version}→{c.to_version} reverted by the owner: {what}",
        )
        s.add(row)
        await s.flush()
        await _close(s, c, "reverted", row.id)
        await s.commit()
    return {"reverted": change_id, "by": row.id}


async def reject_change(change_id: str) -> dict[str, Any]:
    """Stop an engine change still in its gates (status `rejected`, reason "owner")."""
    async with sessionmaker()() as s:
        c = await s.get(AcqChange, change_id)
        if c is None:
            raise NotFound(change_id)
        if c.status not in IN_GATES or c.closed_at is not None:
            raise Conflict(f"only a change in its gates can be rejected (this one is {c.status})")
        c.gates = {**(c.gates or {}), "owner": {"verdict": "rejected", "reason": "owner", "at": _now().isoformat()}}
        await _close(s, c, "rejected", None)
        if c.object_kind == "parser" and c.to_version:
            v = await s.get(ParserVersion, c.to_version)
            if v is not None and v.status in ("draft", "candidate"):
                v.status = "rejected"
        await s.commit()
    return {"rejected": change_id}


async def forbid_similar(change_id: str, days: int | None) -> dict[str, Any]:
    """Forbid similar changes on the engine change's object: a parser is frozen (journalled); a `change_blocks` row
    (object, lever, until) is written when that table exists."""
    until = _now() + timedelta(days=days) if days else None
    async with sessionmaker()() as s:
        c = await s.get(AcqChange, change_id)
        if c is None:
            raise NotFound(change_id)
        kind, key = c.object_kind, c.object_key
        blocks = await _table(s, "change_blocks")
        if blocks:
            await s.execute(
                text(
                    "INSERT INTO change_blocks (object_kind, object_key, lever, until, created_by, reason, created_at) "
                    "VALUES (:k, :o, :l, :u, 'owner', :r, now()) ON CONFLICT (object_kind, object_key, lever) "
                    "DO UPDATE SET until = excluded.until, reason = excluded.reason, created_at = now()"
                ),
                {"k": kind, "o": key, "l": kind, "u": until, "r": f"owner: forbid similar to {c.id}"},
            )
            await s.commit()
    frozen = False
    if kind == "parser":
        await freeze_parser(key, True)
        frozen = True
    elif not blocks:
        raise Conflict(f"similar {kind} changes cannot be forbidden yet (no change_blocks table)")
    return {"object_kind": kind, "object_key": key, "frozen": frozen, "blocked": blocks, "until": until}


# --- Accuracy drill-down ---------------------------------------------------------------------------------------------


async def _baseline(s: Any) -> KpiBaseline | None:
    q = select(KpiBaseline).where(KpiBaseline.ended_at.is_not(None)).order_by(KpiBaseline.ended_at.desc()).limit(1)
    return (await s.execute(q)).scalar_one_or_none()


async def accuracy(days: int = 30) -> dict[str, Any]:
    """The KPI (share of wrong accepted values; gold-checked share) against the baseline, by kind of data, and the
    components to blame ranked by wrong values (click 1)."""
    since = _now() - timedelta(days=max(1, min(days, 365)))
    async with sessionmaker()() as s:
        daily = (
            await s.execute(
                text(
                    "SELECT area, sum(accepted_values), sum(wrong_values), sum(gold_checked), sum(gold_wrong) "
                    "FROM acq_daily WHERE day >= :d GROUP BY area ORDER BY area"
                ),
                {"d": since.date()},
            )
        ).all()
        comp = (
            await s.execute(
                select(
                    TruthSignal.component,
                    func.count().filter(TruthSignal.verdict == "wrong"),
                    func.count().filter(TruthSignal.verdict == "right"),
                    func.max(TruthSignal.created_at),
                )
                .where(
                    TruthSignal.created_at >= since, TruthSignal.component.is_not(None), TruthSignal.disputed.is_(False)
                )
                .group_by(TruthSignal.component)
            )
        ).all()
        reps = {(r.kind, r.key): r for r in (await s.execute(select(ComponentReputation))).scalars()}
        domains = [c.split(":", 1)[1] for c, *_ in comp if c.startswith("source:")]
        caps: dict[str, CapabilityRow] = {}
        for cap in (await s.execute(select(CapabilityRow).where(CapabilityRow.domain.in_(domains)))).scalars():
            if cap.domain not in caps or cap.attempts > caps[cap.domain].attempts:
                caps[cap.domain] = cap
        base = await _baseline(s)
    by_area = []
    acc_n = wrong_n = gold_n = gold_wrong_n = 0
    for area, acc, wrong, gold, gold_wrong in daily:
        acc, wrong, gold, gold_wrong = int(acc or 0), int(wrong or 0), int(gold or 0), int(gold_wrong or 0)
        acc_n, wrong_n, gold_n, gold_wrong_n = acc_n + acc, wrong_n + wrong, gold_n + gold, gold_wrong_n + gold_wrong
        by_area.append(
            {
                "area": area,
                "accepted": acc,
                "wrong": wrong,
                "wrong_share": round(wrong / acc, 4) if acc else None,
                "gold_checked": gold,
                "gold_wrong": gold_wrong,
                "gold_wrong_share": round(gold_wrong / gold, 4) if gold else None,
            }
        )
    base_areas = (
        {str(k): float(v) for k, v in ((base.values or {}).get("accuracy_share_wrong") or {}).items()} if base else {}
    )
    for a in by_area:
        a["baseline"] = base_areas.get(a["area"])
    components = []
    for c, wrong, right, last in comp:
        kind, _, key = c.partition(":")
        if kind == "source":
            cap = caps.get(key)
            lb = cap.acc_lb if cap else None
        else:
            rep = reps.get((kind, key))
            lb = rep.acc_lb if rep else None
        components.append(
            {
                "component": c,
                "kind": kind,
                "key": key,
                "wrong": int(wrong),
                "right": int(right),
                "acc_lb": _f(lb),
                "last_at": last,
            }
        )
    components = sorted((x for x in components if x["wrong"] > 0), key=lambda x: (-x["wrong"], x["component"]))[:100]
    return {
        "days": days,
        "kpi": {
            "wrong_share": round(wrong_n / acc_n, 4) if acc_n else None,
            "gold_wrong_share": round(gold_wrong_n / gold_n, 4) if gold_n else None,
            "accepted": acc_n,
            "wrong": wrong_n,
            "baseline": round(sum(base_areas.values()) / len(base_areas), 4) if base_areas else None,
            "baseline_name": base.name if base else None,
        },
        "by_component": components,
        "by_area": by_area,
    }


def _first(d: dict[str, Any], *keys: str) -> Any:
    return next((d[k] for k in keys if d.get(k) is not None), None)


async def wrong_values(component: str, days: int = 30, limit: int = 200) -> list[dict[str, Any]]:
    """The wrong values blamed on one component (click 2)."""
    since = _now() - timedelta(days=max(1, min(days, 365)))
    async with sessionmaker()() as s:
        q = (
            select(TruthSignal, Claim, Variant)
            .outerjoin(Claim, Claim.id == TruthSignal.claim_id)
            .outerjoin(Variant, Variant.id == TruthSignal.variant_id)
            .where(TruthSignal.component == component, TruthSignal.verdict == "wrong", TruthSignal.created_at >= since)
            .order_by(TruthSignal.created_at.desc())
            .limit(max(1, min(limit, 500)))
        )
        rows = (await s.execute(q)).all()
    out = []
    for sig, claim, variant in rows:
        d = sig.details or {}
        rule = d.get("rule")
        ours = _first(d, "value", "selected", "ours")
        if ours is None and claim is not None:
            ours = claim.value_num if claim.value_num is not None else claim.value_text
        out.append(
            {
                "signal_id": sig.id,
                "variant_id": sig.variant_id,
                "variant": variant.label if variant else None,
                "attribute": sig.attribute,
                "ours": ours,
                "unit": claim.raw_unit if claim else None,
                "truth": _first(d, "gold", "truth", "corrected", "expected"),
                "truth_origin": f"{sig.kind}:{rule}" if rule else sig.kind,
                "blame_vector": sig.blame_vector,
                "claim_id": sig.claim_id,
                "snapshot_id": sig.snapshot_id or (claim.snapshot_id if claim else None),
                "created_at": sig.created_at,
            }
        )
    return out


async def value(claim_id: str) -> dict[str, Any]:
    """One value: the claim, its source, quote, page snapshot, producer and model, and its signals (click 3)."""
    async with sessionmaker()() as s:
        row = (
            await s.execute(
                select(Claim, Evidence, Variant)
                .join(Evidence, Evidence.id == Claim.evidence_id)
                .outerjoin(Variant, Variant.id == Claim.variant_id)
                .where(Claim.id == claim_id)
            )
        ).first()
        if row is None:
            raise NotFound(claim_id)
        c, e, v = row
        sid = c.snapshot_id
        if sid is None:
            sid = (
                await s.execute(
                    select(PageSnapshot.id)
                    .where(PageSnapshot.document_id == e.document_id)
                    .order_by(PageSnapshot.fetched_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
        snap = await s.get(PageSnapshot, sid) if sid else None
        sigs = list(
            (
                await s.execute(
                    select(TruthSignal)
                    .where(TruthSignal.claim_id == claim_id)
                    .order_by(TruthSignal.created_at.desc())
                    .limit(50)
                )
            ).scalars()
        )
    return {
        "claim": {
            "id": c.id,
            "variant_id": c.variant_id,
            "variant": v.label if v else None,
            "attribute": c.attribute,
            "area": c.area,
            "raw_value": c.raw_value,
            "raw_unit": c.raw_unit,
            "value_num": c.value_num,
            "value_text": c.value_text,
            "status": c.status,
            "provenance": c.provenance,
            "reject_rule": c.reject_rule,
            "created_at": c.created_at,
        },
        "evidence": {
            "url": e.url,
            "domain": e.domain,
            "source_type": e.source_type,
            "source_name": e.source_name,
            "retrieved_at": e.retrieved_at,
        },
        "quote": c.excerpt,
        "snapshot": {
            "id": snap.id,
            "fetched_at": snap.fetched_at,
            "url": snap.final_url or snap.url,
            "replayable": snap.replayable,
            "status": snap.status,
        }
        if snap
        else None,
        "producer": c.producer,
        "producer_version": c.producer_version,
        "model": c.model,
        "signals": [
            {
                "id": x.id,
                "at": x.created_at,
                "kind": x.kind,
                "verdict": x.verdict,
                "weight": x.weight,
                "component": x.component,
                "blame_vector": x.blame_vector,
                "details": x.details or {},
            }
            for x in sigs
        ],
    }


def _find(hay: str, needle: str) -> tuple[int, int] | None:
    """Position of the quote in the text: exact, case-insensitive, whitespace-insensitive, then its longest line."""
    if not needle.strip():
        return None
    low = hay.lower()
    for n in (needle, " ".join(needle.split())):
        i = low.find(n.lower())
        if i >= 0:
            return i, len(n)
    parts = sorted((p.strip() for p in needle.splitlines() if len(p.strip()) >= 8), key=len, reverse=True)
    for p in parts:
        i = low.find(p.lower())
        if i >= 0:
            return i, len(p)
    return None


def window(body: str, around: str | None, size: int = TEXT_WINDOW) -> str:
    """At most `size` characters of `body`, centred on the quote when it is found, else its start."""
    hit = _find(body, around or "") if around else None
    if hit is None:
        return body[:size]
    i, n = hit
    start = max(0, min(i - (size - n) // 2, len(body) - size))
    return body[start : start + size]


async def snapshot_text(snapshot_id: str, around: str | None = None) -> str:
    """The stored page reduced to its main content (plain text, never HTML), windowed around the quote."""
    from automind.acquisition.infrastructure.fetch import html_to_text  # noqa: PLC0415
    from automind.acquisition.infrastructure.pages import main_content, pdf_text  # noqa: PLC0415
    from automind.acquisition.snapshots import store  # noqa: PLC0415

    async with sessionmaker()() as s:
        snap = await s.get(PageSnapshot, snapshot_id)
    if snap is None:
        raise NotFound(snapshot_id)
    try:
        raw, url = await store.load(snapshot_id)
    except KeyError as e:
        raise NotFound(snapshot_id) from e
    if "pdf" in (snap.content_type or "").lower() or raw[:5] == b"%PDF-":
        return window(pdf_text(raw), around)
    html = raw.decode("utf-8", errors="replace")
    _, main = main_content(html, url)
    if around and _find(main, around) is None:
        _, plain = html_to_text(html)
        if _find(plain, around) is not None:
            main = plain
    return window(main, around)


# --- Engine status ---------------------------------------------------------------------------------------------------


def _autonomy() -> bool:
    for f in ("agents.yaml", "registry.yaml"):
        try:
            cfg = load_yaml(f)
        except FileNotFoundError:
            continue
        if "autonomy" in cfg:
            return bool(cfg.get("autonomy"))
    return False


async def engine() -> dict[str, Any]:
    """The status strip: the worker's beat, task counts by kind, today's budgets, the baseline, the autonomy flag."""
    from automind.acquisition.worker.budget import CAPS, BudgetGuard  # noqa: PLC0415

    t = _now()
    async with sessionmaker()() as s:
        w = (await s.execute(select(AcqWorker).order_by(AcqWorker.beat_at.desc()).limit(1))).scalar_one_or_none()
        counts = (
            await s.execute(
                text(
                    "SELECT kind, state, count(*), count(*) FILTER (WHERE coalesce(finished_at, created_at) >= :d) "
                    "FROM acq_tasks GROUP BY kind, state"
                ),
                {"d": t - timedelta(hours=24)},
            )
        ).all()
        open_n = (
            await s.execute(
                select(func.count())
                .select_from(AcqChange)
                .where(AcqChange.status.in_(OPEN_CHANGE_STATUSES), AcqChange.closed_at.is_(None))
            )
        ).scalar()
        base = (await s.execute(select(KpiBaseline).order_by(KpiBaseline.started_at.desc()).limit(1))).scalar()
    tasks: dict[str, dict[str, int]] = {}
    running = 0
    for kind, state, n, recent in counts:
        k = tasks.setdefault(kind, {"queued": 0, "running": 0, "failed_24h": 0, "dead": 0})
        if state in ("queued", "running", "dead"):
            k[state] += int(n)
        if state in ("failed", "dead"):
            k["failed_24h"] += int(recent)
        running += int(n) if state == "running" else 0
    try:
        agent_caps = load_yaml("agents.yaml").get("budgets") or {}
    except FileNotFoundError:
        agent_caps = {}
    kinds = sorted(set(CAPS) | set(agent_caps))
    budgets = {}
    for k in kinds:
        g = BudgetGuard(k, float(agent_caps[k]) if k not in CAPS and k in agent_caps else None)
        budgets[k] = {"spent": round(await g.spent(), 4), "limit": g.cap}
    return {
        "worker": {
            "id": w.id,
            "beat_at": w.beat_at,
            "age_s": round((t - w.beat_at).total_seconds()),
            "version": w.version,
            "tasks_done": w.tasks_done,
            "tasks_running": running,
        }
        if w
        else None,
        "tasks": tasks,
        "budgets_today": budgets,
        "baseline": {"name": base.name, "started_at": base.started_at, "ended_at": base.ended_at, "values": base.values}
        if base
        else None,
        "autonomy": _autonomy(),
        "open_changes": int(open_n or 0),
    }
