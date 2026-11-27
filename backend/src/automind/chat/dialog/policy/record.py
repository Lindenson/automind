"""A policy pass as a record and back (spec 015 D5, T221): `record_of` turns a decision into a `DecisionRecord`,
`replay` decides a recorded pass again from its case and config. Pure.

`config_hash` is the sha256 of the config's canonical JSON (sorted keys, no spaces), so one config always has one
hash; `rules_version()` is the sha256 of the rules' names in order and the package version, so a record says which
rules decided it."""

from __future__ import annotations

import hashlib
import json
from functools import cache
from importlib.metadata import PackageNotFoundError, version

from automind.chat.dialog.policy.contracts import Decision, Situation
from automind.chat.dialog.policy.decide import RULES, decide
from automind.chat.dialog.policy.routes import route_of
from automind.chat.domain.case import CaseFile
from automind.chat.domain.decision import DecisionRecord, PolicyConfig, TrailStep
from automind.shared.contracts.json import JsonObject


def canonical(value: object) -> str:
    """`value` as canonical JSON: sorted keys, no spaces, UTF-8 kept."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


@cache
def rules_version() -> str:
    """The sha256 of the rules' names in order and the package version (computed once)."""
    return _sha("|".join(r.name for r in RULES) + "@" + _package_version())


def config_json(cfg: PolicyConfig) -> JsonObject:
    """The config as JSON (money as strings, exact)."""
    return cfg.model_dump(mode="json")


def config_hash(cfg: PolicyConfig) -> str:
    """The sha256 of the config's canonical JSON."""
    return _sha(canonical(config_json(cfg)))


def record_of(d: Decision, s: Situation, cfg: PolicyConfig, *, chat_id: str, turn_id: str,
              case_version: int) -> DecisionRecord:  # fmt: skip
    """The record of pass `s.pass_no`: the situation without its case (stored by `case_version`), the config by its
    hash, the trail, the deciding rule, the action and the node the graph goes to."""
    return DecisionRecord(
        chat_id=chat_id, turn_id=turn_id, pass_no=s.pass_no, case_version=case_version,
        situation=s.model_dump(mode="json", exclude={"case"}), config_hash=config_hash(cfg),
        rules_version=rules_version(), trail=tuple(TrailStep(rule=o.rule, fired=o.fired, why=o.why) for o in d.trail),
        decided_by=d.decided_by, action=d.action.model_dump(mode="json"), next_node=route_of(d.action.kind),
    )  # fmt: skip


def situation_of(rec: DecisionRecord, case: CaseFile) -> Situation:
    """The situation of a recorded pass, with `case` (the case at `rec.case_version`) put back."""
    return Situation.model_validate({**rec.situation, "case": case})


def replay(rec: DecisionRecord, case: CaseFile, cfg: PolicyConfig) -> Decision:
    """The recorded pass decided again by today's rules (the same action unless the rules changed since)."""
    return decide(situation_of(rec, case), cfg)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _package_version() -> str:
    try:
        return version("automind")
    except PackageNotFoundError:  # a source tree run without installing the package
        return "unpackaged"
