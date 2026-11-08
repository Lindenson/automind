"""What the lever checks need now (spec 011 US5, `agents/levers.validate`): the objects with an open change, the
blocks, frozen parsers and sources, reverted changes and whether newer evidence came since, the active prompts, the
rules and the deny-list. Implements `ports.LeverStates`; a database failure becomes `GateStoreUnavailable`."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from automind.acquisition.agents import levers
from automind.acquisition.domain.gates import UNDONE
from automind.acquisition.domain.versions import VersionStatus
from automind.acquisition.gates.application.ports import GateStoreUnavailable
from automind.acquisition.infrastructure import config as acq_config
from automind.acquisition.parsing.infrastructure.v1_specs import denylist
from automind.shared.infrastructure.db.errors import translate_errors
from automind.shared.infrastructure.db.models import OPEN_CHANGE_STATUSES, AcqChange, ChangeBlock, Parser, PromptVersion
from automind.shared.infrastructure.db.session import sessionmaker

_store_errors = translate_errors(GateStoreUnavailable)
_SOURCES = text("SELECT domain, access, frozen FROM sources")
_PARSER_EVIDENCE = text("SELECT max(fetched_at) FROM page_snapshots WHERE parser_version LIKE :p")
_SIGNAL_EVIDENCE = text("SELECT max(created_at) FROM truth_signals")
Reverted = dict[tuple[str, str], list[tuple[str, datetime]]]


class LeverStateRepo:
    """The lever state from the journal, the blocks, the parsers, the sources and the config."""

    @_store_errors
    async def state(self) -> levers.LeverState:
        """The lever state now."""
        now = datetime.now(UTC)
        async with sessionmaker()() as s:
            open_objects = {(k, o) for k, o in (await s.execute(
                select(AcqChange.object_kind, AcqChange.object_key).where(
                    AcqChange.status.in_(OPEN_CHANGE_STATUSES), AcqChange.closed_at.is_(None)))).all()}  # fmt: skip
            blocks = {(b.object_kind, b.object_key, b.lever) for b in (await s.execute(select(ChangeBlock))).scalars()
                      if b.until is None or b.until > now}  # fmt: skip
            frozen_parsers = {r for (r,) in (await s.execute(select(Parser.reader).where(Parser.frozen))).all()}
            src_rows = (await s.execute(_SOURCES)).all()
            reverted = await _reverted(s, now)
            newest = await _newest_evidence(s, reverted)
            q = select(PromptVersion.name, PromptVersion.key).where(PromptVersion.status == VersionStatus.ACTIVE)
            prompts = {n: k for n, k in (await s.execute(q)).all()}
        return levers.LeverState(
            agents_cfg=acq_config.agents_config(), open_objects=open_objects, blocks=blocks,
            frozen_parsers=frozen_parsers, frozen_sources={str(d) for d, _, fr in src_rows if fr}, reverted=reverted,
            newest_evidence=newest, rules=acq_config.effective_rules(),
            sources={str(d): {"access": a, "frozen": fr} for d, a, fr in src_rows}, denylist=tuple(denylist()),
            prompts=prompts,
        )  # fmt: skip


async def _reverted(s: AsyncSession, now: datetime) -> Reverted:
    """(kind, key) -> [(diff hash, when)] of the changes rolled back or reverted."""
    out: Reverted = {}
    q = select(AcqChange.object_kind, AcqChange.object_key, AcqChange.diff_hash, AcqChange.closed_at).where(
        AcqChange.status.in_(list(UNDONE)))  # fmt: skip
    for k, o, h, at in (await s.execute(q)).all():
        out.setdefault((k, o), []).append((h, at or now))
    return out


async def _newest_evidence(s: AsyncSession, reverted: Reverted) -> dict[tuple[str, str], datetime]:
    """Per reverted object, the newest evidence: a page its reader read, or any accuracy signal."""
    out: dict[tuple[str, str], datetime] = {}
    for k, o in reverted:
        if k == "parser":
            got = (await s.execute(_PARSER_EVIDENCE, {"p": f"{o}@v%"})).scalar()
        else:
            got = (await s.execute(_SIGNAL_EVIDENCE)).scalar()
        if got is not None:
            out[(k, o)] = got
    return out
