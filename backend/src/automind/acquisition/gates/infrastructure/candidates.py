"""The candidate object a proposal creates beside its `acq_changes` row, per lever kind (spec 011 US5 T100): a
`parser_versions` candidate, a `prompt_versions` candidate, a `rule_overrides` candidate, an inactive
`role_model_overrides` row; a source goes through the registry's own admission. Runs in the proposal's session."""

from __future__ import annotations

import difflib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from automind.acquisition.agents import levers
from automind.acquisition.gates.domain.change import AGENT, version_text
from automind.acquisition.infrastructure import config as acq_config
from automind.shared.contracts.json import JsonObject
from automind.shared.infrastructure.db.models import (
    Parser,
    ParserVersion,
    PromptVersion,
    RoleModelOverride,
    RuleOverride,
    uid,
)
from automind.shared.infrastructure.llm import gateway as llm_gateway
from automind.shared.provenance.versions import spec_hash

DIFF_CHARS = 20000  # a prompt's unified diff kept in the journal


@dataclass(frozen=True)
class Candidate:
    """The versions a change moves between and what it changes."""

    from_version: str | None
    to_version: str
    diff: JsonObject


async def candidate(s: AsyncSession, change_id: str, agent: str, proposal: BaseModel) -> Candidate:
    """The proposal's candidate object added to the session `s` (the caller commits)."""
    kind, _ = levers.object_of(proposal)
    return await _BY_KIND[kind](s, change_id, agent, proposal)


async def _parser(s: AsyncSession, change_id: str, agent: str, p: BaseModel) -> Candidate:
    assert isinstance(p, levers.ParserProposal)
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
    old = (
        await s.get(ParserVersion, f"{reader}@v{parser.active_version}") if parser.active_version is not None else None
    )
    s.add(ParserVersion(key=spec.key, reader=reader, version=spec.version, spec=body, spec_hash=spec_hash(body),
                        status="candidate", author=AGENT + agent, change_id=change_id))  # fmt: skip
    before = dict(old.spec) if old is not None else {}
    changed = sorted(k for k in set(body) | set(before) if k != "version" and body.get(k) != before.get(k))
    return Candidate(old.key if old is not None else None, spec.key, {"changed": changed, "spec": body})


async def _prompt(s: AsyncSession, change_id: str, agent: str, p: BaseModel) -> Candidate:
    assert isinstance(p, levers.PromptProposal)
    base = await s.get(PromptVersion, p.base_key)
    top = (await s.execute(select(func.max(PromptVersion.version)).where(PromptVersion.name == p.name))).scalar()
    version = int(top or 0) + 1
    key = f"{p.name}@v{version}"
    body = f"<!-- prompt: {p.name} v{version} ({AGENT}{agent}, base {p.base_key}; web reader, no tools). -->\n"
    body += p.text.strip()
    s.add(PromptVersion(key=key, name=p.name, version=version, text=body, text_hash=spec_hash(body),
                        base_key=p.base_key, status="candidate", author=AGENT + agent,
                        change_id=change_id))  # fmt: skip
    old_text = base.text if base is not None else ""
    unified = "".join(difflib.unified_diff(old_text.splitlines(True), body.splitlines(True), p.base_key, key))
    return Candidate(p.base_key, key, {"unified": unified[:DIFF_CHARS]})


async def _rule(s: AsyncSession, change_id: str, agent: str, p: BaseModel) -> Candidate:
    assert isinstance(p, levers.RuleProposal)
    current = levers.rule_value(acq_config.effective_rules(), p.path)
    s.add(RuleOverride(id=uid(), path=p.path, value=p.value, status="candidate", change_id=change_id))
    return Candidate(version_text(current), version_text(p.value), {"path": p.path, "from": current, "to": p.value})


async def _model(s: AsyncSession, change_id: str, agent: str, p: BaseModel) -> Candidate:
    assert isinstance(p, levers.ModelProposal)
    current = llm_gateway.model_name(p.role)
    s.add(RoleModelOverride(id=uid(), role=p.role, model=p.model, change_id=change_id, active=False))
    return Candidate(current, p.model, {"role": p.role, "from": current, "to": p.model})


async def _source(s: AsyncSession, change_id: str, agent: str, p: BaseModel) -> Candidate:
    """The scout's registry entries go through the registry's own admission and `registry_changes` (R15)."""
    assert isinstance(p, levers.SourceProposal)
    return Candidate(None, p.domain, p.model_dump(mode="json"))


_BY_KIND: dict[str, Callable[[AsyncSession, str, str, BaseModel], Awaitable[Candidate]]] = {
    "parser": _parser, "prompt": _prompt, "rule": _rule, "role_model": _model, "source": _source,
}  # fmt: skip
