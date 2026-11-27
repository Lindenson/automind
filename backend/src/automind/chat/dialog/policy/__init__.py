"""Chat · chat.dialog.policy: which action a turn takes next — a fixed, ordered chain of rules (research R5, spec
015). The model never chooses the action.

Owns: `contracts` — `Situation` (everything known in one pass), `CarFacts`, `Rule`, `RuleOutcome`, `Decision`,
  `Stage`, `PolicyInputError`, `PolicyBug`; `rules` — the rules, one module per stage; `decide` — `RULES` in order and
  `decide(situation, config)`; `routes` — `ROUTES` (action kind → node and continuation).
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
from automind.chat.dialog.policy.routes import ROUTES, Continuation, Route, policy_targets, route_of
from automind.chat.dialog.policy.rules.general import wants_candidates

__all__ = [
    "RULES",
    "ROUTES",
    "CarFacts",
    "Continuation",
    "Decision",
    "PolicyBug",
    "PolicyInputError",
    "Route",
    "Rule",
    "RuleOutcome",
    "Situation",
    "Stage",
    "decide",
    "policy_targets",
    "route_of",
    "wants_candidates",
]
