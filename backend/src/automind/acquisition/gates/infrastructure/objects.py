"""The candidate objects going live, back, or away (spec 011 US5): per lever kind, activate (the old object
superseded, kept for rollback), restore (the previous object back) and drop (a candidate that never went live).
Implements `ports.Objects`; a database failure becomes `GateStoreUnavailable`."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from automind.acquisition.domain.gates import ObjectKind
from automind.acquisition.domain.versions import VersionStatus as VS
from automind.acquisition.gates.application.ports import GateStoreUnavailable
from automind.acquisition.gates.domain.change import Change
from automind.shared.contracts.json import JsonObject
from automind.shared.infrastructure.db.errors import translate_errors
from automind.shared.infrastructure.db.models import (
    AcqExperiment,
    Parser,
    ParserVersion,
    PromptVersion,
    RoleModelOverride,
    RuleOverride,
)
from automind.shared.infrastructure.db.session import sessionmaker
from automind.shared.provenance.versions import parse_key

_store_errors = translate_errors(GateStoreUnavailable)
Step = Callable[[AsyncSession, Change, datetime], Awaitable[JsonObject]]


class ObjectRepo:
    """The objects of every lever kind."""

    @_store_errors
    async def activate(self, c: Change, now: datetime) -> JsonObject:
        """The new object live and the experiment marked accepted, in one transaction; returns the previous one."""
        async with sessionmaker()() as s:
            previous = await _ACTIVATE.get(c.object_kind, _none)(s, c, now)
            exp = await s.get(AcqExperiment, c.id)
            if exp is not None:
                exp.phase, exp.started_at, exp.decision, exp.decided_at = "watch", now, "accepted", now
            await s.commit()
        return previous

    @_store_errors
    async def restore(self, c: Change) -> None:
        """The previous object back, the new one rejected."""
        await self._run(_RESTORE, c)

    @_store_errors
    async def drop(self, c: Change) -> None:
        """The candidate rejected."""
        await self._run(_DROP, c)

    async def _run(self, steps: dict[str, Step], c: Change) -> None:
        async with sessionmaker()() as s:
            await steps.get(c.object_kind, _none)(s, c, datetime.now(UTC))
            await s.commit()


def _previous(c: Change) -> JsonObject:
    return dict((c.gates.get("accept") or {}).get("previous") or {})


async def _none(s: AsyncSession, c: Change, now: datetime) -> JsonObject:
    return {}


async def _parser_activate(s: AsyncSession, c: Change, now: datetime) -> JsonObject:
    reader, version = parse_key(str(c.to_version))
    old = await s.get(ParserVersion, c.from_version) if c.from_version else None
    previous: JsonObject = {"key": c.from_version, "status": old.status if old is not None else None}
    if old is not None:
        old.status = VS.SUPERSEDED
    await s.execute(update(ParserVersion).where(ParserVersion.key == c.to_version)
                    .values(status=VS.ACTIVE, activated_at=now, zero_streak=0))  # fmt: skip
    await s.execute(update(Parser).where(Parser.reader == reader).values(active_version=version))
    return previous


async def _parser_restore(s: AsyncSession, c: Change, now: datetime) -> JsonObject:
    reader, _ = parse_key(str(c.to_version))
    await s.execute(update(ParserVersion).where(ParserVersion.key == c.to_version).values(status=VS.REJECTED))
    old_version = None
    if c.from_version:
        _, old_version = parse_key(c.from_version)
        await s.execute(update(ParserVersion).where(ParserVersion.key == c.from_version)
                        .values(status=_previous(c).get("status") or VS.ACTIVE))  # fmt: skip
    await s.execute(update(Parser).where(Parser.reader == reader).values(active_version=old_version))
    return {}


async def _parser_drop(s: AsyncSession, c: Change, now: datetime) -> JsonObject:
    await s.execute(update(ParserVersion).where(ParserVersion.key == c.to_version, ParserVersion.status == VS.CANDIDATE)
                    .values(status=VS.REJECTED))  # fmt: skip
    return {}


async def _prompt_activate(s: AsyncSession, c: Change, now: datetime) -> JsonObject:
    await s.execute(update(PromptVersion).where(PromptVersion.name == c.object_key, PromptVersion.status == VS.ACTIVE)
                    .values(status=VS.SUPERSEDED))  # fmt: skip
    await s.execute(update(PromptVersion).where(PromptVersion.key == c.to_version)
                    .values(status=VS.ACTIVE, activated_at=now))  # fmt: skip
    return {"key": c.from_version}


async def _prompt_restore(s: AsyncSession, c: Change, now: datetime) -> JsonObject:
    await s.execute(update(PromptVersion).where(PromptVersion.key == c.to_version).values(status=VS.REJECTED))
    if c.from_version:
        await s.execute(update(PromptVersion).where(PromptVersion.key == c.from_version).values(status=VS.ACTIVE))
    return {}


async def _prompt_drop(s: AsyncSession, c: Change, now: datetime) -> JsonObject:
    await s.execute(update(PromptVersion).where(PromptVersion.key == c.to_version, PromptVersion.status == VS.CANDIDATE)
                    .values(status=VS.REJECTED))  # fmt: skip
    return {}


async def _rule_activate(s: AsyncSession, c: Change, now: datetime) -> JsonObject:
    q = select(RuleOverride).where(RuleOverride.path == c.object_key, RuleOverride.status == VS.ACTIVE)
    old = (await s.execute(q)).scalar_one_or_none()
    if old is not None:
        old.status = VS.SUPERSEDED
        await s.flush()
    await s.execute(
        update(RuleOverride).where(RuleOverride.change_id == c.id).values(status=VS.ACTIVE, activated_at=now)
    )
    return {"id": old.id if old is not None else None}


async def _rule_restore(s: AsyncSession, c: Change, now: datetime) -> JsonObject:
    await s.execute(update(RuleOverride).where(RuleOverride.change_id == c.id).values(status=VS.REJECTED))
    await s.flush()
    if prev := _previous(c).get("id"):
        await s.execute(update(RuleOverride).where(RuleOverride.id == prev).values(status=VS.ACTIVE))
    return {}


async def _rule_drop(s: AsyncSession, c: Change, now: datetime) -> JsonObject:
    await s.execute(update(RuleOverride).where(RuleOverride.change_id == c.id, RuleOverride.status == VS.CANDIDATE)
                    .values(status=VS.REJECTED))  # fmt: skip
    return {}


async def _model_activate(s: AsyncSession, c: Change, now: datetime) -> JsonObject:
    q = select(RoleModelOverride).where(RoleModelOverride.role == c.object_key, RoleModelOverride.active)
    old = (await s.execute(q)).scalar_one_or_none()
    if old is not None:
        old.active = False
        await s.flush()
    await s.execute(update(RoleModelOverride).where(RoleModelOverride.change_id == c.id).values(active=True))
    return {"id": old.id if old is not None else None}


async def _model_restore(s: AsyncSession, c: Change, now: datetime) -> JsonObject:
    await s.execute(update(RoleModelOverride).where(RoleModelOverride.change_id == c.id).values(active=False))
    await s.flush()
    if prev := _previous(c).get("id"):
        await s.execute(update(RoleModelOverride).where(RoleModelOverride.id == prev).values(active=True))
    return {}


K = ObjectKind
_ACTIVATE: dict[str, Step] = {K.PARSER: _parser_activate, K.PROMPT: _prompt_activate, K.RULE: _rule_activate,
                              K.ROLE_MODEL: _model_activate}  # fmt: skip
_RESTORE: dict[str, Step] = {K.PARSER: _parser_restore, K.PROMPT: _prompt_restore, K.RULE: _rule_restore,
                             K.ROLE_MODEL: _model_restore}  # fmt: skip
_DROP: dict[str, Step] = {K.PARSER: _parser_drop, K.PROMPT: _prompt_drop, K.RULE: _rule_drop}
