"""The change journal of the gates (spec 011 US5 T100, FR-019, research R15): `acq_changes` rows and the candidate
objects behind them.

`propose()` checks the proposal against the levers (`agents/levers.validate`) and, in one transaction, inserts the
candidate object (`parser_versions` candidate, `prompt_versions` candidate, `rule_overrides` candidate,
`role_model_overrides` inactive) and the `acq_changes` row `proposed` — the partial unique index keeps one open
change per object — then queues `gate_replay:<id>`. Every transition (`advance`, `accept`, `keep`, `reject`,
`abandon`, `rollback`) updates `gates`, the metrics and the one-sentence `explanation` (built by
`domain/gates.explain`), and counts `automind_acq_changes_total{agent,status}`. Accepting activates the new object and
supersedes the old one (kept for rollback); rolling back restores it and journals a `system` row.
"""

from __future__ import annotations

import difflib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from automind.acquisition.agents import levers
from automind.acquisition.domain import gates, relevance_audit
from automind.acquisition.domain.versions import parse_key, spec_hash
from automind.infrastructure import config
from automind.infrastructure.db import (
    OPEN_CHANGE_STATUSES,
    AcqChange,
    AcqExperiment,
    ChangeBlock,
    Parser,
    ParserVersion,
    PromptVersion,
    RoleModelOverride,
    RuleOverride,
    sessionmaker,
    uid,
)

log = logging.getLogger(__name__)
AGENT = "agent:"


def agent_of(change: AcqChange) -> str:
    return change.author.removeprefix(AGENT)


def _now() -> datetime:
    return datetime.now(UTC)


# --- the state the lever checks need ------------------------------------------------------------------------------


async def lever_state() -> levers.LeverState:
    from automind.acquisition.parsing.migrate_v1 import denylist  # noqa: PLC0415

    now = _now()
    async with sessionmaker()() as s:
        open_objects = {(k, o) for k, o in (await s.execute(
            select(AcqChange.object_kind, AcqChange.object_key).where(
                AcqChange.status.in_(OPEN_CHANGE_STATUSES), AcqChange.closed_at.is_(None)))).all()}  # fmt: skip
        blocks = {(b.object_kind, b.object_key, b.lever) for b in (await s.execute(select(ChangeBlock))).scalars()
                  if b.until is None or b.until > now}  # fmt: skip
        frozen_parsers = {r for (r,) in (await s.execute(select(Parser.reader).where(Parser.frozen))).all()}
        src_rows = (await s.execute(text("SELECT domain, access, frozen FROM sources"))).all()
        reverted: dict[tuple[str, str], list[tuple[str, datetime]]] = {}
        for k, o, h, at in (await s.execute(
            select(AcqChange.object_kind, AcqChange.object_key, AcqChange.diff_hash, AcqChange.closed_at).where(
                AcqChange.status.in_(("rolled_back", "reverted"))))).all():  # fmt: skip
            reverted.setdefault((k, o), []).append((h, at or now))
        newest: dict[tuple[str, str], datetime] = {}
        for k, o in reverted:  # newer evidence: a page the object's reader read, or any accuracy signal
            if k == "parser":
                q = text("SELECT max(fetched_at) FROM page_snapshots WHERE parser_version LIKE :p")
                got = (await s.execute(q, {"p": f"{o}@v%"})).scalar()
            else:
                got = (await s.execute(text("SELECT max(created_at) FROM truth_signals"))).scalar()
            if got is not None:
                newest[(k, o)] = got
        prompts = {n: k for n, k in (await s.execute(
            select(PromptVersion.name, PromptVersion.key).where(PromptVersion.status == "active"))).all()}  # fmt: skip
    return levers.LeverState(
        agents_cfg=config.agents_config(), open_objects=open_objects, blocks=blocks, frozen_parsers=frozen_parsers,
        frozen_sources={str(d) for d, _, fr in src_rows if fr}, reverted=reverted, newest_evidence=newest,
        rules=config.effective_rules(), sources={str(d): {"access": a, "frozen": fr} for d, a, fr in src_rows},
        denylist=tuple(denylist()), prompts=prompts,
    )  # fmt: skip


async def check(agent: str, proposal: BaseModel) -> list[str]:
    """Every reason the levers refuse this proposal now; [] = it may be proposed."""
    return levers.validate(agent, proposal, await lever_state())


# --- candidate objects per lever kind -----------------------------------------------------------------------------


@dataclass
class Candidate:
    from_version: str | None
    to_version: str
    diff: dict[str, Any]


async def _parser_candidate(s: AsyncSession, change_id: str, agent: str, p: levers.ParserProposal) -> Candidate:
    reader = p.spec.reader
    parser = await s.get(Parser, reader)
    if parser is None:
        parser = Parser(reader=reader, domains=list(p.spec.domains), page_type=p.spec.page_type, active_version=None,
                        frozen=False)  # fmt: skip
        s.add(parser)
        await s.flush()
    top = (await s.execute(select(func.max(ParserVersion.version)).where(ParserVersion.reader == reader))).scalar()
    spec = p.spec.model_copy(update={"version": int(top or 0) + 1})
    body = spec.model_dump(mode="json")
    old = None
    if parser.active_version is not None:
        old = await s.get(ParserVersion, f"{reader}@v{parser.active_version}")
    s.add(ParserVersion(key=spec.key, reader=reader, version=spec.version, spec=body, spec_hash=spec_hash(body),
                        status="candidate", author=AGENT + agent, change_id=change_id))  # fmt: skip
    before = dict(old.spec) if old is not None else {}
    changed = sorted(k for k in set(body) | set(before) if k != "version" and body.get(k) != before.get(k))
    return Candidate(old.key if old is not None else None, spec.key, {"changed": changed, "spec": body})


async def _prompt_candidate(s: AsyncSession, change_id: str, agent: str, p: levers.PromptProposal) -> Candidate:
    base = await s.get(PromptVersion, p.base_key)
    top = (await s.execute(select(func.max(PromptVersion.version)).where(PromptVersion.name == p.name))).scalar()
    version = int(top or 0) + 1
    key = f"{p.name}@v{version}"
    body = f"<!-- prompt: {p.name} v{version} ({AGENT}{agent}, base {p.base_key}; web reader, no tools). -->\n"
    body += p.text.strip()
    s.add(
        PromptVersion(
            key=key,
            name=p.name,
            version=version,
            text=body,
            text_hash=spec_hash(body),
            base_key=p.base_key,
            status="candidate",
            author=AGENT + agent,
            change_id=change_id,
        )
    )
    old_text = base.text if base is not None else ""
    unified = "".join(difflib.unified_diff(old_text.splitlines(True), body.splitlines(True), p.base_key, key))
    return Candidate(p.base_key, key, {"unified": unified[:20000]})


async def _rule_candidate(s: AsyncSession, change_id: str, agent: str, p: levers.RuleProposal) -> Candidate:
    current = levers.rule_value(config.effective_rules(), p.path)
    s.add(RuleOverride(id=uid(), path=p.path, value=p.value, status="candidate", change_id=change_id))
    return Candidate(_text(current), _text(p.value), {"path": p.path, "from": current, "to": p.value})


async def _model_candidate(s: AsyncSession, change_id: str, agent: str, p: levers.ModelProposal) -> Candidate:
    from automind.infrastructure import llm_gateway  # noqa: PLC0415

    current = llm_gateway.model_name(p.role)
    s.add(RoleModelOverride(id=uid(), role=p.role, model=p.model, change_id=change_id, active=False))
    return Candidate(current, p.model, {"role": p.role, "from": current, "to": p.model})


async def _source_candidate(s: AsyncSession, change_id: str, agent: str, p: levers.SourceProposal) -> Candidate:
    """The scout's registry entries go through the registry's own admission and `registry_changes` (R15)."""
    return Candidate(None, p.domain, p.model_dump(mode="json"))


def _text(v: Any) -> str:
    """A version column (80 characters): a number, or a keyword list (the words, cut)."""
    if v is None or (isinstance(v, list) and not v):
        return "none"
    s = ", ".join(map(str, v)) if isinstance(v, list) else f"{v:g}" if isinstance(v, float) else str(v)
    return s if len(s) <= 80 else s[:79] + "…"


CandidateFn = Callable[[AsyncSession, str, str, Any], Awaitable[Candidate]]
CANDIDATES: dict[str, CandidateFn] = {
    "parser": _parser_candidate,
    "prompt": _prompt_candidate,
    "rule": _rule_candidate,
    "role_model": _model_candidate,
    "source": _source_candidate,
}


# --- the counter and the gauges -----------------------------------------------------------------------------------


def _count(agent: str, status: str) -> None:
    try:
        from automind.acquisition.worker import exporter  # noqa: PLC0415

        exporter.CHANGES.labels(agent=agent, status=status).inc()
    except Exception:  # noqa: BLE001 - metrics are best effort
        log.debug("journal.count_failed", exc_info=True)


async def publish_gauges() -> None:
    """automind_acq_open_changes{agent,phase} and automind_agent_spend_today_eur{agent}."""
    from automind.acquisition.agents import budget  # noqa: PLC0415
    from automind.acquisition.worker import exporter  # noqa: PLC0415

    async with sessionmaker()() as s:
        rows = (await s.execute(
            select(AcqChange.author, AcqChange.status, func.count()).where(
                AcqChange.status.in_(OPEN_CHANGE_STATUSES), AcqChange.closed_at.is_(None))
            .group_by(AcqChange.author, AcqChange.status))).all()  # fmt: skip
    caps = {a: c for a in budget.AGENTS if (c := budget.cap(a)) is not None}
    exporter.set_changes({(a.removeprefix(AGENT), st): float(n) for a, st, n in rows}, await budget.spend_by_agent(),
                         caps)  # fmt: skip


# --- transitions --------------------------------------------------------------------------------------------------


def facts(c: AcqChange, status: str | None = None, gate: str | None = None) -> gates.Facts:
    ev = c.evidence or {}
    extra: dict[str, Any] = {}
    measured = relevance_audit.RelevanceMeasure.from_dict(((c.gates or {}).get("replay") or {}).get("relevance"))
    if measured is not None:  # a relevance keyword change: the replay numbers are the re-judged pages
        extra["measure"] = relevance_audit.sentence_part(measured)
    return gates.Facts(c.object_kind, c.object_key, c.from_version, c.to_version, str(ev.get("trigger") or c.reason),
                       status or c.status, gate, extra)  # fmt: skip


def metrics_of(c: AcqChange, gate: str, which: str = "metrics_new") -> gates.Metrics | None:
    got = ((c.gates or {}).get(gate) or {}).get(which)
    return gates.Metrics.from_report(got) if got else None


def sentence(c: AcqChange, status: str | None = None, gate: str | None = None,
             verdict: gates.Verdict | None = None, **kw: Any) -> str:  # fmt: skip
    old, new = metrics_of(c, "shadow", "metrics_old"), metrics_of(c, "shadow")
    shadow = (old, new) if old is not None and new is not None else None
    return gates.explain(facts(c, status, gate), replay=metrics_of(c, "replay"), shadow=shadow, verdict=verdict, **kw)


async def propose(agent: str, proposal: BaseModel, reason: str, evidence: dict[str, Any] | None = None, *,
                  cost_eur: float = 0.0) -> str | None:  # fmt: skip
    """Journal a proposal and queue its replay gate; None when the levers refuse it or the object has an open
    change (the refusal is logged)."""
    from automind.acquisition.worker import queue  # noqa: PLC0415

    errs = await check(agent, proposal)
    if errs:
        log.info("journal.refused agent=%s %s", agent, "; ".join(errs))
        _count(agent, "refused")
        return None
    kind, key = levers.object_of(proposal)
    change_id = uid()
    now = _now()
    try:
        async with sessionmaker()() as s:
            cand = await CANDIDATES[kind](s, change_id, agent, proposal)
            change = AcqChange(
                id=change_id, created_at=now, author=AGENT + agent, object_kind=kind, object_key=key,
                from_version=cand.from_version, to_version=cand.to_version, diff=cand.diff,
                diff_hash=levers.diff_hash(proposal), reason=reason, evidence=dict(evidence or {}), gates={},
                status="proposed", explanation="", cost_eur=cost_eur,
            )  # fmt: skip
            change.explanation = sentence(change)
            s.add(change)
            await s.commit()
    except IntegrityError:
        log.info("journal.open_change agent=%s %s %s", agent, kind, key)
        _count(agent, "refused")
        return None
    _count(agent, "proposed")
    log.info("journal.proposed %s", change.explanation, extra={"event": "change.proposed", "change_id": change_id})
    await queue.enqueue("gate_replay", {"change_id": change_id, "agent": agent}, dedupe_key=f"gate_replay:{change_id}")
    return change_id


async def load(change_id: str) -> AcqChange | None:
    async with sessionmaker()() as s:
        return await s.get(AcqChange, change_id)


async def _update(change_id: str, **values: Any) -> AcqChange:
    async with sessionmaker()() as s:
        c = await s.get(AcqChange, change_id)
        if c is None:
            raise KeyError(change_id)
        for k, v in values.items():
            setattr(c, k, v)
        await s.commit()
        await s.refresh(c)
        return c


def _gate(c: AcqChange, gate: str, verdict: gates.Verdict, old: gates.Metrics | None, new: gates.Metrics | None,
          **extra: Any) -> dict[str, Any]:  # fmt: skip
    g = dict(c.gates or {})
    g[gate] = {**verdict.as_dict(), "metrics_old": old.as_dict() if old else None,
               "metrics_new": new.as_dict() if new else None, "at": _now().isoformat(), **extra}  # fmt: skip
    return g


async def advance(change_id: str, phase: str, gate: str, verdict: gates.Verdict, old: gates.Metrics | None = None,
                  new: gates.Metrics | None = None, **extra: Any) -> AcqChange:  # fmt: skip
    """Record a gate result and move the change to `phase` (replay, shadow)."""
    c = await load(change_id)
    assert c is not None
    c.gates = _gate(c, gate, verdict, old, new, **extra)
    c.status = phase
    c = await _update(change_id, gates=c.gates, status=phase, metrics_before=old.as_dict() if old else c.metrics_before,
                      explanation=sentence(c, phase))  # fmt: skip
    _count(agent_of(c), phase)
    return c


async def _claim(change_id: str, expected: tuple[str, ...], status: str) -> AcqChange | None:
    """Move an open change from one of `expected` to `status` atomically; None when another task moved it first."""
    async with sessionmaker()() as s:
        got = (await s.execute(update(AcqChange).where(AcqChange.id == change_id, AcqChange.status.in_(expected),
                                                       AcqChange.closed_at.is_(None))
                               .values(status=status).returning(AcqChange.id))).scalar_one_or_none()  # fmt: skip
        await s.commit()
    return await load(change_id) if got else None


async def _close(change_id: str, status: str, gate: str, verdict: gates.Verdict, old: gates.Metrics | None,
                 new: gates.Metrics | None, **extra: Any) -> AcqChange:  # fmt: skip
    c = await _claim(change_id, ("proposed", "replay", "shadow", "watch"), status)
    if c is None:
        return await load(change_id)  # type: ignore[return-value]
    c.gates = _gate(c, gate, verdict, old, new, **extra)
    async with sessionmaker()() as s:
        await DEACTIVATE[c.object_kind](s, c)
        await s.commit()
    c = await _update(change_id, gates=c.gates, status=status, closed_at=_now(),
                      explanation=sentence(c, status, gate, verdict))  # fmt: skip
    _count(agent_of(c), status)
    log.info("journal.%s %s", status, c.explanation, extra={"event": f"change.{status}", "change_id": change_id})
    return c


async def reject(change_id: str, gate: str, verdict: gates.Verdict, old: gates.Metrics | None = None,
                 new: gates.Metrics | None = None, **extra: Any) -> AcqChange:  # fmt: skip
    return await _close(change_id, "rejected", gate, verdict, old, new, **extra)


async def abandon(change_id: str, gate: str, verdict: gates.Verdict, old: gates.Metrics | None = None,
                  new: gates.Metrics | None = None, **extra: Any) -> AcqChange:  # fmt: skip
    return await _close(change_id, "abandoned", gate, verdict, old, new, **extra)


async def accept(change_id: str, verdict: gates.Verdict, old: gates.Metrics, new: gates.Metrics,
                 **extra: Any) -> AcqChange:  # fmt: skip
    """Shadow passed: activate the new object (the old one is superseded, kept for rollback) and start the watch."""
    c = await _claim(change_id, ("shadow",), "watch")
    if c is None:
        return await load(change_id)  # type: ignore[return-value]
    c.gates = _gate(c, "shadow", verdict, old, new, **extra)
    async with sessionmaker()() as s:
        previous = await ACTIVATE[c.object_kind](s, c)
        exp = await s.get(AcqExperiment, change_id)
        if exp is not None:
            exp.phase, exp.started_at, exp.decision, exp.decided_at = "watch", _now(), "accepted", _now()
        await s.commit()
    c.gates["accept"] = {"at": _now().isoformat(), "previous": previous}
    c = await _update(change_id, gates=c.gates, status="watch", metrics_after=new.as_dict(),
                      explanation=sentence(c, "accepted"))  # fmt: skip
    _count(agent_of(c), "accepted")
    log.info("journal.accepted %s", c.explanation, extra={"event": "change.accepted", "change_id": change_id})
    return c


async def keep(change_id: str, verdict: gates.Verdict, current: gates.Metrics) -> AcqChange:
    c = await _claim(change_id, ("watch",), "kept")
    if c is None:
        return await load(change_id)  # type: ignore[return-value]
    c.gates = _gate(c, "watch", verdict, metrics_of(c, "shadow"), current)
    c = await _update(change_id, gates=c.gates, status="kept", closed_at=_now(), explanation=sentence(c, "kept"))
    _count(agent_of(c), "kept")
    return c


async def rollback(change_id: str, by: str, verdict: gates.Verdict, current: gates.Metrics | None = None, *,
                   wrong_signals: int = 0, days: float | None = None) -> AcqChange:  # fmt: skip
    """Restore the previous object; the change becomes `rolled_back` and a closed `system` (or owner) row journals
    the restore, linked by `reverted_by`."""
    c = await _claim(change_id, ("watch",), "rolled_back")
    if c is None:
        return await load(change_id)  # type: ignore[return-value]
    c.gates = _gate(c, "watch", verdict, metrics_of(c, "shadow"), current)
    async with sessionmaker()() as s:
        await RESTORE[c.object_kind](s, c)
        await s.commit()
    explanation = sentence(c, "rolled_back", verdict=verdict, wrong_signals=wrong_signals, days=days)
    row_id, now = uid(), _now()
    async with sessionmaker()() as s:
        s.add(AcqChange(id=row_id, created_at=now, author=by, object_kind=c.object_kind, object_key=c.object_key,
                        from_version=c.to_version, to_version=c.from_version,
                        diff={"rollback_of": change_id}, diff_hash=c.diff_hash, reason="rollback",
                        evidence={"verdict": verdict.as_dict(), "wrong_signals": wrong_signals}, gates={},
                        status="accepted", explanation=explanation, cost_eur=0, closed_at=now))  # fmt: skip
        await s.commit()
    c = await _update(change_id, gates=c.gates, status="rolled_back", closed_at=now, reverted_by=row_id,
                      explanation=explanation)  # fmt: skip
    _count(agent_of(c), "rolled_back")
    log.warning("journal.rolled_back %s", explanation, extra={"event": "change.rolled_back", "change_id": change_id})
    return c


# --- activating, restoring and dropping the objects ----------------------------------------------------------------


async def _parser_activate(s: AsyncSession, c: AcqChange) -> dict[str, Any]:
    reader, version = parse_key(str(c.to_version))
    old = await s.get(ParserVersion, c.from_version) if c.from_version else None
    previous = {"key": c.from_version, "status": old.status if old is not None else None}
    if old is not None:
        old.status = "superseded"
    await s.execute(update(ParserVersion).where(ParserVersion.key == c.to_version)
                    .values(status="active", activated_at=_now(), zero_streak=0))  # fmt: skip
    await s.execute(update(Parser).where(Parser.reader == reader).values(active_version=version))
    return previous


async def _parser_restore(s: AsyncSession, c: AcqChange) -> None:
    reader, _ = parse_key(str(c.to_version))
    prev = ((c.gates or {}).get("accept") or {}).get("previous") or {}
    await s.execute(update(ParserVersion).where(ParserVersion.key == c.to_version).values(status="rejected"))
    if c.from_version:
        _, old_version = parse_key(c.from_version)
        await s.execute(update(ParserVersion).where(ParserVersion.key == c.from_version)
                        .values(status=prev.get("status") or "active"))  # fmt: skip
        await s.execute(update(Parser).where(Parser.reader == reader).values(active_version=old_version))
    else:
        await s.execute(update(Parser).where(Parser.reader == reader).values(active_version=None))


async def _parser_drop(s: AsyncSession, c: AcqChange) -> None:
    await s.execute(
        update(ParserVersion)
        .where(ParserVersion.key == c.to_version, ParserVersion.status == "candidate")
        .values(status="rejected")
    )


async def _prompt_activate(s: AsyncSession, c: AcqChange) -> dict[str, Any]:
    await s.execute(update(PromptVersion).where(PromptVersion.name == c.object_key, PromptVersion.status == "active")
                    .values(status="superseded"))  # fmt: skip
    await s.execute(update(PromptVersion).where(PromptVersion.key == c.to_version)
                    .values(status="active", activated_at=_now()))  # fmt: skip
    return {"key": c.from_version}


async def _prompt_restore(s: AsyncSession, c: AcqChange) -> None:
    await s.execute(update(PromptVersion).where(PromptVersion.key == c.to_version).values(status="rejected"))
    if c.from_version:
        await s.execute(update(PromptVersion).where(PromptVersion.key == c.from_version).values(status="active"))


async def _prompt_drop(s: AsyncSession, c: AcqChange) -> None:
    await s.execute(
        update(PromptVersion)
        .where(PromptVersion.key == c.to_version, PromptVersion.status == "candidate")
        .values(status="rejected")
    )


async def _rule_activate(s: AsyncSession, c: AcqChange) -> dict[str, Any]:
    old = (
        await s.execute(select(RuleOverride).where(RuleOverride.path == c.object_key, RuleOverride.status == "active"))
    ).scalar_one_or_none()
    if old is not None:
        old.status = "superseded"
        await s.flush()
    await s.execute(update(RuleOverride).where(RuleOverride.change_id == c.id)
                    .values(status="active", activated_at=_now()))  # fmt: skip
    return {"id": old.id if old is not None else None}


async def _rule_restore(s: AsyncSession, c: AcqChange) -> None:
    prev = ((c.gates or {}).get("accept") or {}).get("previous") or {}
    await s.execute(update(RuleOverride).where(RuleOverride.change_id == c.id).values(status="rejected"))
    await s.flush()
    if prev.get("id"):
        await s.execute(update(RuleOverride).where(RuleOverride.id == prev["id"]).values(status="active"))


async def _rule_drop(s: AsyncSession, c: AcqChange) -> None:
    await s.execute(update(RuleOverride).where(RuleOverride.change_id == c.id, RuleOverride.status == "candidate")
                    .values(status="rejected"))  # fmt: skip


async def _model_activate(s: AsyncSession, c: AcqChange) -> dict[str, Any]:
    old = (await s.execute(select(RoleModelOverride).where(RoleModelOverride.role == c.object_key,
                                                           RoleModelOverride.active))).scalar_one_or_none()  # fmt: skip
    if old is not None:
        old.active = False
        await s.flush()
    await s.execute(update(RoleModelOverride).where(RoleModelOverride.change_id == c.id).values(active=True))
    return {"id": old.id if old is not None else None}


async def _model_restore(s: AsyncSession, c: AcqChange) -> None:
    prev = ((c.gates or {}).get("accept") or {}).get("previous") or {}
    await s.execute(update(RoleModelOverride).where(RoleModelOverride.change_id == c.id).values(active=False))
    await s.flush()
    if prev.get("id"):
        await s.execute(update(RoleModelOverride).where(RoleModelOverride.id == prev["id"]).values(active=True))


async def _noop(s: AsyncSession, c: AcqChange) -> Any:
    return {}


ACTIVATE: dict[str, Callable[[AsyncSession, AcqChange], Awaitable[Any]]] = {
    "parser": _parser_activate, "prompt": _prompt_activate, "rule": _rule_activate, "role_model": _model_activate,
    "source": _noop,
}  # fmt: skip
RESTORE: dict[str, Callable[[AsyncSession, AcqChange], Awaitable[Any]]] = {
    "parser": _parser_restore, "prompt": _prompt_restore, "rule": _rule_restore, "role_model": _model_restore,
    "source": _noop,
}  # fmt: skip
DEACTIVATE: dict[str, Callable[[AsyncSession, AcqChange], Awaitable[Any]]] = {
    "parser": _parser_drop, "prompt": _prompt_drop, "rule": _rule_drop, "role_model": _noop, "source": _noop,
}  # fmt: skip
