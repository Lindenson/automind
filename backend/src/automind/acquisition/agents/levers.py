"""The data levers agents may pull, and the code that checks every proposal before any gate (spec 011 US5, FR-017,
FR-020, research R13; constitution XII).

An agent's output is one of the proposal models below — data validated by Pydantic, never code. `validate(agent,
proposal, state)` lists every reason to refuse it (empty = may enter the gates):
- an agent targets only its own lever kinds (`LEVERS`);
- never the deny-list, robots/terms fields (`sources.access`, `access_evidence`), budgets, frozen parsers or sources,
  the chat's prompts, code or files: the levers below have no field that could name them;
- rule paths only from `config/agents.yaml: levers.rule_auditor.paths`, within `bounds` and `max_step_rel` of the
  current value; prompts only `levers.extractor_tuner.prompts`; models only `allowed_models` for
  `levers.extractor_tuner.roles`;
- one change per object (an open change refuses), the owner's `change_blocks`, and a reverted change's `diff_hash`
  is not proposed again for the object without newer evidence.

Other branches add levers with `register_lever()` (the scout registers its registry lever this way).
"""

from __future__ import annotations

import fnmatch
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from automind.acquisition.parsing.spec import ParserSpec, regex_problem
from automind.shared.provenance.versions import parse_key, spec_hash

MAX_PROMPT_CHARS = 20_000
MAX_KEYWORDS = 40
MAX_NEW_KEYWORDS = 5
_WORD = re.compile(r"^[\w][\w .'-]{0,39}$", re.UNICODE)
_DOMAIN = re.compile(r"^(?=.{4,120}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}$")
# never a lever, whatever a config says: the human-only parts of the system (constitution XII)
FORBIDDEN_PATH_PARTS = ("denylist", "access", "access_evidence", "budget", "budgets", "frozen", "daily_cap",
                        "robots", "terms", "allowed_models", "levers")  # fmt: skip
AREAS = ("specs", "engineering", "measured", "price", "maintenance", "reliability", "reviews", "used_price",
         "depreciation", "manufacturer", "incentives")  # fmt: skip
MARKETS = ("ES", "EN", "DE", "FR", "IT", "PT", "NL", "ANY")


class _Proposal(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ParserProposal(_Proposal):
    kind: Literal["parser"] = "parser"
    spec: ParserSpec


class RuleProposal(_Proposal):
    kind: Literal["rule"] = "rule"
    path: str = Field(min_length=3, max_length=160)
    value: float | list[str]


class PromptProposal(_Proposal):
    kind: Literal["prompt"] = "prompt"
    name: str = Field(pattern=r"^[a-z_]{2,40}$")
    text: str = Field(min_length=50, max_length=MAX_PROMPT_CHARS)
    base_key: str


class ModelProposal(_Proposal):
    kind: Literal["role_model"] = "role_model"
    role: str
    model: str = Field(max_length=80)


class SourceProposal(_Proposal):
    kind: Literal["source"] = "source"
    domain: str
    area: str
    market: str
    url_patterns: list[str] = Field(default_factory=list, max_length=10)


Proposal = ParserProposal | RuleProposal | PromptProposal | ModelProposal | SourceProposal


@dataclass
class LeverState:
    """What the checks need to know about the world, gathered by the journal (or built by a test)."""

    agents_cfg: Mapping[str, Any]
    open_objects: set[tuple[str, str]] = field(default_factory=set)
    blocks: set[tuple[str, str, str]] = field(default_factory=set)  # (object_kind, object_key, lever) in force
    frozen_parsers: set[str] = field(default_factory=set)
    frozen_sources: set[str] = field(default_factory=set)
    reverted: dict[tuple[str, str], list[tuple[str, datetime]]] = field(default_factory=dict)  # hash, reverted_at
    newest_evidence: dict[tuple[str, str], datetime] = field(default_factory=dict)
    rules: Mapping[str, Any] = field(default_factory=dict)  # effective rules: {"plausibility": …, "sense": …, …}
    sources: Mapping[str, Mapping[str, Any]] | None = None  # registry domain -> {access, frozen, status}
    denylist: tuple[str, ...] = ()
    prompts: Mapping[str, str] = field(default_factory=dict)  # name -> active version key


@dataclass(frozen=True)
class Lever:
    kind: str  # the acq_changes object_kind
    model: type[BaseModel]
    agents: tuple[str, ...]
    object_key: Callable[[Any], str]
    diff: Callable[[Any], Any]  # what the diff_hash is taken of
    check: Callable[[Any, LeverState], list[str]]


LEVERS: dict[str, Lever] = {}


def register_lever(lever: Lever) -> None:
    """Add (or replace) a lever kind; object kinds are those of `acq_changes` (parser, prompt, role_model, rule,
    source)."""
    LEVERS[lever.kind] = lever


def lever_of(proposal: BaseModel) -> Lever:
    kind = str(getattr(proposal, "kind", ""))
    if kind not in LEVERS:
        raise ValueError(f"no lever {kind!r}")
    return LEVERS[kind]


def object_of(proposal: BaseModel) -> tuple[str, str]:
    lv = lever_of(proposal)
    return lv.kind, lv.object_key(proposal)


def diff_hash(proposal: BaseModel) -> str:
    return spec_hash(lever_of(proposal).diff(proposal))


# --- per-lever checks ---------------------------------------------------------------------------------------------


def _levers_cfg(state: LeverState, agent: str) -> Mapping[str, Any]:
    return dict((state.agents_cfg.get("levers") or {}).get(agent) or {})


def _parser_check(p: ParserProposal, state: LeverState) -> list[str]:
    errs = [f"spec: {e}" for e in p.spec.check(state.sources, state.denylist)]
    if p.spec.reader in state.frozen_parsers:
        errs.append(f"parser {p.spec.reader} is frozen by the owner")
    return errs


def _segments_match(path: str, pattern: str) -> bool:
    a, b = path.split("."), pattern.split(".")
    return len(a) == len(b) and all(fnmatch.fnmatchcase(x, y) for x, y in zip(a, b, strict=True))


def rule_value(rules: Mapping[str, Any], path: str) -> Any:
    """The current value at a dotted path; `.min`/`.max` also index a `[min, max]` pair (plausibility.yaml)."""
    node: Any = rules
    for part in path.split("."):
        if isinstance(node, Mapping):
            node = node.get(part)
        elif isinstance(node, (list, tuple)) and len(node) == 2 and part in ("min", "max"):
            node = node[0 if part == "min" else 1]
        else:
            return None
        if node is None:
            return None
    return node


def _bounds(cfg: Mapping[str, Any], path: str) -> tuple[float | None, float | None]:
    for pattern, b in (cfg.get("bounds") or {}).items():
        if _segments_match(path, str(pattern)):
            return (b.get("min"), b.get("max")) if isinstance(b, Mapping) else (None, None)
    return 0.0, None  # thresholds are never negative unless the owner says so


def _rule_check(p: RuleProposal, state: LeverState) -> list[str]:
    cfg = _levers_cfg(state, "rule_auditor")
    lowered = p.path.lower()
    if any(part in FORBIDDEN_PATH_PARTS for part in lowered.split(".")):
        return [f"path {p.path} touches a human-only setting"]
    if not any(_segments_match(p.path, str(g)) for g in cfg.get("paths") or []):
        return [f"path {p.path} is not in levers.rule_auditor.paths"]
    current = rule_value(state.rules, p.path)
    if p.path.startswith("relevance.keywords."):
        return _keywords_check(p, current)
    if isinstance(p.value, list):
        return [f"path {p.path} takes a number"]
    if not isinstance(current, int | float) or isinstance(current, bool):
        return [f"path {p.path} has no current numeric value to change"]
    errs = []
    step = float(cfg.get("max_step_rel", 0.2))
    if current == 0 or abs(p.value - current) / abs(current) > step + 1e-9:
        errs.append(f"step {current}→{p.value} is more than {step:.0%} of the current value")
    if p.value == current:
        errs.append("the value does not change")
    lo, hi = _bounds(cfg, p.path)
    if lo is not None and p.value < lo:
        errs.append(f"value {p.value} below the bound {lo}")
    if hi is not None and p.value > hi:
        errs.append(f"value {p.value} above the bound {hi}")
    return errs


def _keywords_check(p: RuleProposal, current: Any) -> list[str]:
    if not isinstance(p.value, list):
        return [f"path {p.path} takes a list of keywords"]
    errs = [f"keyword {w!r} is not a plain word or phrase" for w in p.value if not _WORD.match(w)]
    if len(p.value) > MAX_KEYWORDS:
        errs.append(f"more than {MAX_KEYWORDS} keywords")
    before = {str(w).lower() for w in (current or [])}
    added = {w.lower() for w in p.value} - before
    if len(added) > MAX_NEW_KEYWORDS:
        errs.append(f"{len(added)} new keywords in one step (at most {MAX_NEW_KEYWORDS})")
    if not added and before == {w.lower() for w in p.value}:
        errs.append("the keywords do not change")
    return errs


def _prompt_check(p: PromptProposal, state: LeverState) -> list[str]:
    cfg = _levers_cfg(state, "extractor_tuner")
    if p.name not in (cfg.get("prompts") or []):
        return [f"prompt {p.name} is not in levers.extractor_tuner.prompts"]
    errs = []
    try:
        base, _ = parse_key(p.base_key)
        if base != p.name:
            errs.append(f"base {p.base_key} is not a version of {p.name}")
    except ValueError:
        errs.append(f"base {p.base_key!r} is not a version key")
    active = state.prompts.get(p.name)
    if active is not None and p.base_key != active:
        errs.append(f"base {p.base_key} is not the active version {active}")
    if "untrusted_document" not in p.text:
        errs.append("the prompt must keep the rule that the document is untrusted data")
    if "<!--" in p.text:
        errs.append("the prompt header is written by code")
    return errs


def _model_check(p: ModelProposal, state: LeverState) -> list[str]:
    cfg = _levers_cfg(state, "extractor_tuner")
    errs = []
    if p.role not in (cfg.get("roles") or []):
        errs.append(f"role {p.role} is not in levers.extractor_tuner.roles")
    if p.model not in (state.agents_cfg.get("allowed_models") or []):
        errs.append(f"model {p.model} is not in allowed_models")
    return errs


def denied(domain: str, deny: Iterable[str]) -> bool:
    return any(d and d.lower() in domain for d in deny)


def _source_check(p: SourceProposal, state: LeverState) -> list[str]:
    d = p.domain.strip().lower()
    errs = []
    if not _DOMAIN.match(d):
        errs.append(f"{p.domain!r} is not a registrable domain")
    if denied(d, state.denylist):
        errs.append(f"domain {d} is on the deny-list")
    if d in state.frozen_sources:
        errs.append(f"source {d} is frozen by the owner")
    if p.area not in AREAS:
        errs.append(f"unknown area {p.area!r}")
    if p.market not in MARKETS:
        errs.append(f"unknown market {p.market!r}")
    errs += [f"url_patterns {pat[:60]!r}: {e}" for pat in p.url_patterns if (e := regex_problem(pat))]
    return errs


def _parser_diff(p: ParserProposal) -> Any:
    return p.spec.model_dump(mode="json", exclude={"version", "notes"})


register_lever(Lever("parser", ParserProposal, ("parser_doctor",), lambda p: p.spec.reader, _parser_diff,
                     _parser_check))  # fmt: skip
register_lever(Lever("rule", RuleProposal, ("rule_auditor",), lambda p: p.path,
                     lambda p: {"path": p.path, "value": p.value}, _rule_check))  # fmt: skip
register_lever(Lever("prompt", PromptProposal, ("extractor_tuner",), lambda p: p.name,
                     lambda p: {"name": p.name, "text": p.text}, _prompt_check))  # fmt: skip
register_lever(Lever("role_model", ModelProposal, ("extractor_tuner",), lambda p: p.role,
                     lambda p: {"role": p.role, "model": p.model}, _model_check))  # fmt: skip
register_lever(Lever("source", SourceProposal, ("scout",), lambda p: p.domain.strip().lower(),
                     lambda p: {"domain": p.domain.strip().lower(), "area": p.area, "market": p.market,
                                "url_patterns": sorted(p.url_patterns)}, _source_check))  # fmt: skip


# --- the check ----------------------------------------------------------------------------------------------------


def validate(agent: str, proposal: BaseModel, state: LeverState) -> list[str]:
    """Every reason to refuse `agent`'s proposal; [] = it may enter the gates."""
    try:
        lv = lever_of(proposal)
    except ValueError as e:
        return [str(e)]
    if not isinstance(proposal, lv.model):
        return [f"proposal is not a {lv.model.__name__}"]
    if agent not in lv.agents:
        return [f"agent {agent} may not change {lv.kind} objects"]
    kind, key = lv.kind, lv.object_key(proposal)
    errs: list[str] = []
    if (kind, key) in state.open_objects:
        errs.append(f"{kind} {key} has an open change (one change per object)")
    if any(b[0] == kind and b[1] == key and b[2] in (kind, "*") for b in state.blocks):
        errs.append(f"{kind} {key}: similar changes forbidden by the owner")
    h = diff_hash(proposal)
    newest = state.newest_evidence.get((kind, key))
    for rh, at in state.reverted.get((kind, key), []):
        if rh == h and (newest is None or newest <= at):
            errs.append(f"{kind} {key}: this change was reverted on {at:%Y-%m-%d} and there is no newer evidence")
    return errs + lv.check(proposal, state)
