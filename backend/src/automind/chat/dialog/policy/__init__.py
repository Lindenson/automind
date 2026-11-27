"""Chat · chat.dialog.policy: which action a turn takes next — a fixed, ordered chain of rules (research R5, spec
015). The model never chooses the action.

Owns: `contracts` — `Situation` (everything known in one pass), `CarFacts`, `Rule`, `RuleOutcome`, `Decision`,
  `Stage`, `PolicyInputError`, `PolicyBug`; `rules` — the rules, one module per stage; `decide` — `RULES` in order and
  `decide(situation, config)`; `routes` — `ROUTES` (action kind → node and continuation); `situation` —
  `situation_from` (the facts of a pass from the turn state, checked against the invariants); `record` —
  `record_of`, `replay`, `config_hash`, `rules_version`; `why` — `render_why`; `export` — `fixture`, `mask` (spec
  015 PL3).
Flow: understand → assess → Situation → decide → Decision → the graph routes on its action through `ROUTES`.
Depends on: chat.domain. Must not depend on: chat.dialog.nodes, chat.dialog.graph, chat.application,
  chat.infrastructure, shared.infrastructure, langgraph, sqlalchemy (import contract `policy-pure`).
Public API: the names below.
"""

from automind.chat.dialog.policy.contracts import (
    CarFacts,
    Decision,
    PolicyBug,
    PolicyInputError,
    Rule,
    RuleOutcome,
    Situation,
    Stage,
)
from automind.chat.dialog.policy.decide import RULES, decide
from automind.chat.dialog.policy.export import fixture, mask
from automind.chat.dialog.policy.record import config_hash, config_json, record_of, replay, rules_version
from automind.chat.dialog.policy.routes import ROUTES, Continuation, Route, policy_targets, route_of
from automind.chat.dialog.policy.rules.general import wants_candidates
from automind.chat.dialog.policy.situation import PolicyFacts, SituationRead, situation_from
from automind.chat.dialog.policy.why import render_why

__all__ = [
    "RULES",
    "ROUTES",
    "CarFacts",
    "Continuation",
    "Decision",
    "PolicyFacts",
    "PolicyBug",
    "PolicyInputError",
    "Route",
    "Rule",
    "RuleOutcome",
    "Situation",
    "SituationRead",
    "Stage",
    "config_hash",
    "config_json",
    "decide",
    "fixture",
    "mask",
    "policy_targets",
    "record_of",
    "render_why",
    "replay",
    "rules_version",
    "route_of",
    "situation_from",
    "wants_candidates",
]
